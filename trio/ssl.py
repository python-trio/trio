# General theory of operation:
#
# We implement an API that closely mirrors the stdlib ssl module's blocking
# API, and we do it using the stdlib ssl module's non-blocking in-memory API.
# The stdlib non-blocking in-memory API is barely documented, and acts as a
# thin wrapper around openssl, whose documentation also leaves something to be
# desired. So here's the main things you need to know to understand the code
# in this file:
#
# We use an ssl.SSLObject, which exposes the four main I/O operations:
#
# - do_handshake: performs the initial handshake. Must be called once at the
#   beginning of each connection; is a no-op once it's completed once.
#
# - write: takes some unencrypted data and attempts to send it to the remote
#   peer.

# - read: attempts to decrypt and return some data from the remote peer.
#
# - unwrap: this is weirdly named; maybe it helps to realize that the thing it
#   wraps is called SSL_shutdown. It sends a cryptographically signed message
#   saying "I'm closing this connection now", and then waits to receive the
#   same from the remote peer (unless we already received one, in which case
#   it returns immediately).
#
# All of these operations read and write from some in-memory buffers called
# "BIOs", which are an opaque OpenSSL-specific object that's basically
# semantically equivalent to a Python bytearray. When they want to send some
# bytes to the remote peer, they append them to the outgoing BIO, and when
# they want to receive some bytes from the remote peer, they try to pull them
# out of the incoming BIO. "Sending" always succeeds, because the outgoing BIO
# can always be extended to hold more data. "Receiving" acts sort of like a
# non-blocking socket: it might manage to get some data immediately, or it
# might fail and need to be tried again later. We can also directly add or
# remove data from the BIOs whenever we want.
#
# Now the problem is that while these I/O operations are opaque atomic
# operations from the point of view of us calling them, under the hood they
# might require some arbitrary sequence of sends and receives from the remote
# peer. This is particularly true for do_handshake, which generally requires a
# few round trips, but it's also true for write and read, due to an evil thing
# called "renegotiation".
#
# Renegotiation is the process by which one of the peers might arbitrarily
# decide to redo the handshake at any time. Did I mention it's evil? It's
# pretty evil, and almost universally hated. The HTTP/2 spec forbids the use
# of TLS renegotiation for HTTP/2 connections. TLS 1.3 removes it from the
# protocol entirely. It's impossible to trigger a renegotiation if using
# Python's ssl module. OpenSSL's renegotiation support is pretty buggy [1].
# Nonetheless, it does get used in real life, mostly in two cases:
#
# 1) Normally in TLS 1.2 and below, when the client side of a connection wants
# to present a certificate to prove their identity, that certificate gets sent
# in plaintext. This is bad, because it means that anyone eavesdropping can
# see who's connecting – it's like sending your username in plain text. Not as
# bad as sending your password in plain text, but still, pretty bad. However,
# renegotiations *are* encrypted. So as a workaround, it's not uncommon for
# systems that want to use client certificates to first do an anonymous
# handshake, and then to turn around and do a second handshake (=
# renegotiation) and this time ask for a client cert. Or sometimes this is
# done on a case-by-case basis, e.g. a web server might accept a connection,
# read the request, and then once it sees the page you're asking for it might
# stop and ask you for a certificate.
#
# 2) In principle the same TLS connection can be used for an arbitrarily long
# time, and might transmit arbitrarily large amounts of data. But this creates
# a cryptographic problem: an attacker who has access to arbitrarily large
# amounts of data that's all encrypted using the same key may eventually be
# able to use this to figure out the key. Is this a real practical problem? I
# have no idea, I'm not a cryptographer. In any case, some people worry that
# it's a problem, so their TLS libraries are designed to automatically trigger
# a renegotation every once in a while on some sort of timer.
#
# The end result is that you might be going along, minding your own business,
# and then *bam*! a wild renegotiation appears! And you just have to cope.
#
# The reason that coping with renegotiations is difficult is that some
# unassuming "read" or "write" call might find itself unable to progress until
# it does a handshake, which remember is a process with multiple round
# trips. So read might have to send data, and write might have to receive
# data, and this might happen multiple times. And some of those attempts might
# fail because there isn't any data yet, and need to be retried. Managing all
# this is pretty complicated.
#
# Here's how openssl (and thus the stdlib ssl module) handle this. All of the
# I/O operations above follow the same rules. When you call one of them:
#
# - it might write some data to the outgoing BIO
# - it might read some data from the incoming BIO
# - it might raise SSLWantReadError if it can't complete without reading more
#   data from the incoming BIO. This is important: the "read" in ReadError
#   refers to reading from the *underlying* stream.
# - (and in principle it might raise SSLWantWriteError too, but that never
#   happens when using memory BIOs, so never mind)
#
# If it doesn't raise an error, then the operation completed successfully
# (though we still need to take any outgoing data out of the memory buffer and
# put it onto the wire). If it *does* raise an error, then we need to retry
# *exactly that method call* later – in particular, if a 'write' failed, we
# need to try again later *with the same data*, because openssl might have
# already committed some of the initial parts of our data to its output even
# though it didn't tell us that, and has remembered that the next time we call
# write it needs to skip the first 1024 bytes or whatever it is. (Well,
# technically, we're actually allowed to call 'write' again with a data buffer
# which is the same as our old one PLUS some extra stuff added onto the end,
# but in trio that never comes up so never mind.)
#
# There are some people online who claim that once you've gotten a Want*Error
# then the *very next call* you make to openssl *must* be the same as the
# previous one. I'm pretty sure those people are wrong. In particular, it's
# okay to call write, get a WantReadError, and then call read a few times;
# it's just that *the next time you call write*, it has to be with the same
# data.
#
# One final wrinkle: we want our SSLStream to support full-duplex operation,
# i.e. it should be possible for one task to be calling sendall while another
# task is calling recv. But renegotiation makes this a big hassle, because
# even if SSLStream's restricts themselves to one task calling sendall and one
# task calling recv, those two tasks might end up both wanting to call
# sendall, or both to call recv at the same time *on the underlying
# stream*. So we have to do some careful locking to hide this problem from our
# users.
#
# (Renegotiation is evil.)
#
# So our basic strategy is to define a single helper method called "_retry",
# which has generic logic for dealing with SSLWantReadError, pushing data from
# the outgoing BIO to the wire, reading data from the wire to the incoming
# BIO, retrying an I/O call until it works, and synchronizing with other tasks
# that might be calling _retry concurrently. Basically it takes an SSLObject
# non-blocking in-memory method and converts it into a trio async blocking
# method. _retry is only about 30 lines of code, but all these cases
# multiplied by concurrent calls make it extremely tricky, so there are lots
# of comments down below on the details, and a really extensive test suite in
# test_ssl.py. And now you know *why* it's so tricky, and can probably
# understand how it works.
#
# [1] https://rt.openssl.org/Ticket/Display.html?id=3712

# XX how closely should we match the stdlib API?
# - maybe suppress_ragged_eofs=False is a better default?
# - maybe check crypto folks for advice?
# - this is also interesting: https://bugs.python.org/issue8108#msg102867

# Definitely keep an eye on Cory's TLS API ideas on security-sig etc.

# XX document behavior on cancellation/error (i.e.: all is lost abandon
# stream)
# docs will need to make very clear that this is different from all the other
# cancellations in core trio

import ssl as _stdlib_ssl

from . import _core
from .abc import Stream as _Stream
from . import _sync
from ._util import UnLock as _UnLock

__all__ = ["SSLStream"]

def _reexport(name):
    globals()[name] = getattr(_stdlib_ssl, name)
    __all__.append(name)

for _name in [
        "SSLError", "SSLZeroReturnError", "SSLSyscallError", "SSLEOFError",
        "CertificateError", "create_default_context", "match_hostname",
        "cert_time_to_seconds", "DER_cert_to_PEM_cert", "PEM_cert_to_DER_cert",
        "get_default_verify_paths", "SSLContext", "Purpose",
]:
    _reexport(_name)

# Windows only
try:
    for _name in ["enum_certificates", "enum_crls"]:
        _reexport(_name)
except AttributeError:
    pass

try:
    # 3.6+ only:
    for _name in [
            "SSLSession", "VerifyMode", "VerifyFlags", "Options",
            "AlertDescription", "SSLErrorNumber",
    ]:
        _reexport(_name)
except AttributeError:
    pass

for _name in _stdlib_ssl.__dict__.keys():
    if _name == _name.upper():
        _reexport(_name)

# XX add suppress_ragged_eofs option?
# or maybe actually make an option that means "I want the variant of the
# protocol that doesn't do EOFs", so it ignores lack from the other side and
# also doesn't send them.

class _Once:
    def __init__(self, afn, *args):
        self._afn = afn
        self._args = args
        self._started = False
        self._done = _sync.Event()

    async def ensure(self, *, checkpoint):
        if not self._started:
            self._started = True
            await self._afn(*self._args)
            self._done.set()
        elif not checkpoint and self._done.is_set():
            return
        else:
            await self._done.wait()


class SSLStream(_Stream):
    def __init__(
            self, transport_stream, sslcontext, *, bufsize=32 * 1024, **kwargs):
        self.transport_stream = transport_stream
        self._bufsize = bufsize
        self._outgoing = _stdlib_ssl.MemoryBIO()
        self._incoming = _stdlib_ssl.MemoryBIO()
        self._ssl_object = sslcontext.wrap_bio(
            self._incoming, self._outgoing, **kwargs)
        # Tracks whether we've already done the initial handshake
        self._handshook = _Once(self._do_handshake)

        # These are used to synchronize access to self.transport_stream
        self._inner_send_lock = _sync.Lock()
        self._inner_recv_count = 0
        self._inner_recv_lock = _sync.Lock()

        # These are used to make sure that our caller doesn't attempt to make
        # multiple concurrent calls to sendall/wait_sendall_might_not_block or to recv.
        self._outer_send_lock = _UnLock(
            RuntimeError,
            "another task is currently sending data on this SSLStream")
        self._outer_recv_lock = _UnLock(
            RuntimeError,
            "another task is currently receiving data on this SSLStream")

    _forwarded = {
        "context", "server_side", "server_hostname", "session",
        "session_reused", "getpeercert", "selected_npn_protocol", "cipher",
        "shared_ciphers", "compression", "pending", "get_channel_binding",
        "selected_alpn_protocol", "version",
    }
    def __getattr__(self, name):
        if name in self._forwarded:
            return getattr(self._ssl_object, name)
        else:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        if name in self._forwarded:
            setattr(self._ssl_object, name, value)
        else:
            super().__setattr__(name, value)

    def __dir__(self):
        return super().__dir__() + list(self._forwarded)

    # This is probably the single trickiest function in trio. It has lots of
    # comments, though, just make sure to think carefully if you ever have to
    # touch it. The big comment at the top of this file will help explain
    # too.
    async def _retry(self, fn, *args):
        await _core.yield_if_cancelled()
        yielded = False
        try:
            finished = False
            while not finished:
                # WARNING: this code needs to be very careful with when it
                # calls 'await'! There might be multiple tasks calling this
                # function at the same time trying to do different operations,
                # so we need to be careful to:
                #
                # 1) interact with the SSLObject, then
                # 2) await on exactly one thing that lets us make forward
                # progress, then
                # 3) loop or exit
                #
                # In particular we don't want to yield while interacting with
                # the SSLObject (because it's shared state, so someone else
                # might come in and mess with it while we're suspended), and
                # we don't want to yield *before* starting the operation that
                # will help us make progress, because then someone else might
                # come in and

                # Call the SSLObject method, and get its result.
                #
                # NB: despite what the docs, say SSLWantWriteError can't
                # happen – "Writes to memory BIOs will always succeed if
                # memory is available: that is their size can grow
                # indefinitely."
                # https://wiki.openssl.org/index.php/Manual:BIO_s_mem(3)
                want_read = False
                try:
                    ret = fn(*args)
                except _stdlib_ssl.SSLWantReadError:
                    want_read = True
                else:
                    finished = True
                to_send = self._outgoing.read()

                # Outputs from the above code block are:
                #
                # - to_send: bytestring; if non-empty then we need to send
                #   this data to make forward progress
                #
                # - want_read: True if we need to recv some data to make
                #   forward progress
                #
                # - finished: False means that we need to retry the call to
                #   fn(*args) again, after having pushed things forward. True
                #   means we still need to do whatever was said (in particular
                #   send any data in to_send), but once we do then we're
                #   done.
                #
                # - ret: the operation's return value. (Meaningless unless
                #   finished is True.)
                #
                # Invariant: want_read and finished can't both be True at the
                # same time.
                #
                # Now we need to move things forward. There are two things we
                # might have to do, and any given operation might require
                # either, both, or neither to proceed:
                #
                # - send the data in to_send
                #
                # - recv some data and put it into the incoming BIO
                #
                # Our strategy is: if there's data to send, send it;
                # *otherwise* if there's data to recv, recv it.
                #
                # If both need to happen, then we only send. Why? Well, we
                # know that *right now* we have to both send and recv before
                # the operation can complete. But as soon as we yield, that
                # information becomes potentially stale – e.g. while we're
                # sending, some other task might go and recv the data we need
                # and put it into the incoming BIO. And if it does, then we
                # *definitely don't* want to do a recv – there might not be
                # any more data coming, and we'd deadlock! We could do
                # something tricky to keep track of whether a recv happens
                # while we're sending, but the case where we have to do both
                # is very unusual (only during a renegotation), so it's better
                # to keep things simple. So we do just one
                # potentially-blocking operation, then check again for fresh
                # information.
                #
                # And we prioritize sending over receiving because, if there
                # are multiple tasks that want to recv, then it doesn't matter
                # what order they go in. But if there are multiple tasks that
                # want to send, then they each have different data, and the
                # data needs to get put onto the wire in the same order that
                # it was retrieved from the outgoing BIO. So if we have data
                # to send, that *needs* to be the *very* *next* *thing* we do,
                # to make sure no-one else sneaks in before us. Or if we can't
                # send immediately because someone else is, then we at least
                # need to get in line immediately.
                if to_send:
                    # NOTE: This relies on the lock being strict FIFO fair!
                    async with self._inner_send_lock:
                        yielded = True
                        await self.transport_stream.sendall(to_send)
                elif want_read:
                    # It's possible that someone else is already blocked
                    # in transport_stream.recv. If so then we want to wait for
                    # them to finish, but we don't want to call
                    # transport_stream.recv again ourselves; we just want to
                    # loop around and check if their contribution helped
                    # anything. So we make a note of how many times some task
                    # has been through here before taking the lock, and if
                    # it's changed by the time we get the lock, then we skip
                    # calling transport_stream.recv and loop around
                    # immediately.
                    recv_count = self._inner_recv_count
                    async with self._inner_recv_lock:
                        yielded = True
                        if recv_count == self._inner_recv_count:
                            data = await self.transport_stream.recv(self._bufsize)
                            if not data:
                                self._incoming.write_eof()
                            else:
                                self._incoming.write(data)
                            self._inner_recv_count += 1
            return ret
        finally:
            if not yielded:
                await _core.yield_briefly_no_cancel()

    async def _do_handshake(self):
        await self._retry(self._ssl_object.do_handshake)

    # XX wrong name? or I guess if we ever gain the ability to explicitly
    # renegotiate then this could slightly change semantics to ensure that
    # it's been driven to completion? But it's weird given that if a
    # renegotiation is in progress it doesn't push it forward... OTOH this is
    # how the stdlib ssl do_handshake works too.
    async def do_handshake(self):
        """Ensure that the initial handshake has completed.

        The SSL protocol requires an initial handshake to exchange
        certificates, select cryptographic keys, and so forth, before any
        actual data can be sent or received. You don't have to call this
        method; if you don't, then :class:`SSLStream` will automatically
        peform the handshake as needed, the first time you try to send or
        receive data. But if you want to trigger it manually – for example,
        because you want to look at the peer's certificate before you start
        talking to them – then you can call this method.

        If the initial handshake is already in progress in another task, this
        waits for it to complete and then returns.

        If the initial handshake has already completed, this returns
        immediately without doing anything (except executing a checkpoint).

        """
        await self._handshook.ensure(checkpoint=True)

    # Most things work if we don't explicitly force do_handshake to be called
    # before calling recv or sendall, because openssl will automatically
    # perform the handshake on the first SSL_{read,write} call. BUT, allowing
    # openssl to do this will disable Python's hostname checking!!! See:
    #   https://bugs.python.org/issue30141
    # So we *definitely* have to make sure that do_handshake is called
    # before doing anything else.
    async def recv(self, bufsize):
        async with self._outer_recv_lock:
            await self._handshook.ensure(checkpoint=False)
            return await self._retry(self._ssl_object.read, bufsize)

    async def sendall(self, data):
        async with self._outer_send_lock:
            await self._handshook.ensure(checkpoint=False)
            # SSLObject interprets write(b"") as an EOF for some reason, which
            # is not what we want.
            if not data:
                await _core.yield_briefly()
                return
            return await self._retry(self._ssl_object.write, data)

    # Question: should this take outer_send_lock and/or outer_recv_lock? I
    # initially thought it should, because it doesn't make sense to unwrap a
    # stream that you're in the middle of using. But then I thought, this is
    # also called by graceful_close(), and it *is* generally expected that you
    # can close a stream that's in active use. But, actually in trio that
    # generally leads to freezes (epoll and kqueue don't give any way to
    # detect that an fd you're waiting on has been closed :-( :-( :-(), so
    # maybe it's actually better to error out...?
    async def unwrap(self):
        async with self._outer_recv_lock, self._outer_send_lock:
            if self.transport_stream is None:
                raise RuntimeError("can't unwrap an already-closed SSLStream")
            await self._handshook.ensure(checkpoint=False)
            await self._retry(self._ssl_object.unwrap)
            transport_stream = self.transport_stream
            self.transport_stream = None
            return (transport_stream, self._incoming.read())

    def forceful_close(self):
        if self.transport_stream is not None:
            self.transport_stream.forceful_close()
            self.transport_stream = None

    async def graceful_close(self):
        transport_stream = self.transport_stream
        if transport_stream is None:
            await _core.yield_briefly()
            return
        try:
            # Do the TLS goodbye exchange
            await self.unwrap()
            # Close the underlying stream
            await transport_stream.graceful_close()
        except:
            transport_stream.forceful_close()
            raise

    async def wait_sendall_might_not_block(self):
        # This method's implementation is deceptively simple.
        #
        # First, we take the outer send lock, because of trio's standard
        # semantics that wait_sendall_might_not_block and sendall conflict.
        async with self._outer_send_lock:
            # Then we take the inner send lock. We know that no other tasks
            # are calling self.sendall or self.wait_sendall_might_not_block, because we have
            # the outer_send_lock. But! There might be another task calling
            # self.recv -> transport_stream.sendall, in which case if we were to
            # call transport_stream.wait_sendall_might_not_block directly we'd have two tasks
            # doing write-related operations on transport_stream simultaneously,
            # which is not allowed. We *don't* want to raise this conflict to
            # our caller, because it's purely an internal affair – all they
            # did was call wait_sendall_might_not_block and recv at the same time, which is
            # totally valid. And waiting for the lock is OK, because a call to
            # sendall certainly wouldn't complete while the other task holds
            # the lock.
            async with self._inner_send_lock:
                # Now we have the lock, which creates another potential
                # problem: what if a call to self.recv attempts to do
                # transport_stream.sendall now? It'll have to wait for us to
                # finish! But that's OK, because we release the lock as soon
                # as the underlying stream becomes writable, and the self.recv
                # call wasn't going to make any progress until then anyway.
                #
                # Of course, this does mean we might return *before* the
                # stream is logically writable, because immediately after we
                # return self.recv might write some data and make it
                # non-writable again. But that's OK too, wait_sendall_might_not_block only
                # guarantees that it doesn't return late.
                await self.transport_stream.wait_sendall_might_not_block()
                print(self._inner_send_lock.statistics())
