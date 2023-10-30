from __future__ import annotations

import operator as _operator
import ssl as _stdlib_ssl
from collections.abc import Awaitable, Callable
from enum import Enum as _Enum
from typing import Any, ClassVar, Final as TFinal, Generic, TypeVar

import trio

from . import _sync
from ._highlevel_generic import aclose_forcefully
from ._util import ConflictDetector, final
from .abc import Listener, Stream

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
# a renegotiation every once in a while on some sort of timer.
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
# but in Trio that never comes up so never mind.)
#
# There are some people online who claim that once you've gotten a Want*Error
# then the *very next call* you make to openssl *must* be the same as the
# previous one. I'm pretty sure those people are wrong. In particular, it's
# okay to call write, get a WantReadError, and then call read a few times;
# it's just that *the next time you call write*, it has to be with the same
# data.
#
# One final wrinkle: we want our SSLStream to support full-duplex operation,
# i.e. it should be possible for one task to be calling send_all while another
# task is calling receive_some. But renegotiation makes this a big hassle, because
# even if SSLStream's restricts themselves to one task calling send_all and one
# task calling receive_some, those two tasks might end up both wanting to call
# send_all, or both to call receive_some at the same time *on the underlying
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
# non-blocking in-memory method and converts it into a Trio async blocking
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
# cancellations in core Trio


T = TypeVar("T")

################################################################
# SSLStream
################################################################

# Ideally, when the user calls SSLStream.receive_some() with no argument, then
# we should do exactly one call to self.transport_stream.receive_some(),
# decrypt everything we got, and return it. Unfortunately, the way openssl's
# API works, we have to pick how much data we want to allow when we call
# read(), and then it (potentially) triggers a call to
# transport_stream.receive_some(). So at the time we pick the amount of data
# to decrypt, we don't know how much data we've read. As a simple heuristic,
# we record the max amount of data returned by previous calls to
# transport_stream.receive_some(), and we use that for future calls to read().
# But what do we use for the very first call? That's what this constant sets.
#
# Note that the value passed to read() is a limit on the amount of
# *decrypted* data, but we can only see the size of the *encrypted* data
# returned by transport_stream.receive_some(). TLS adds a small amount of
# framing overhead, and TLS compression is rarely used these days because it's
# insecure. So the size of the encrypted data should be a slight over-estimate
# of the size of the decrypted data, which is exactly what we want.
#
# The specific value is not really based on anything; it might be worth tuning
# at some point. But, if you have an TCP connection with the typical 1500 byte
# MTU and an initial window of 10 (see RFC 6928), then the initial burst of
# data will be limited to ~15000 bytes (or a bit less due to IP-level framing
# overhead), so this is chosen to be larger than that.
STARTING_RECEIVE_SIZE: TFinal = 16384


def _is_eof(exc: BaseException | None) -> bool:
    # There appears to be a bug on Python 3.10, where SSLErrors
    # aren't properly translated into SSLEOFErrors.
    # This stringly-typed error check is borrowed from the AnyIO
    # project.
    return isinstance(exc, _stdlib_ssl.SSLEOFError) or (
        "UNEXPECTED_EOF_WHILE_READING" in getattr(exc, "strerror", ())
    )


class NeedHandshakeError(Exception):
    """Some :class:`SSLStream` methods can't return any meaningful data until
    after the handshake. If you call them before the handshake, they raise
    this error.

    """


class _Once:
    def __init__(self, afn: Callable[..., Awaitable[object]], *args: object) -> None:
        self._afn = afn
        self._args = args
        self.started = False
        self._done = _sync.Event()

    async def ensure(self, *, checkpoint: bool) -> None:
        if not self.started:
            self.started = True
            await self._afn(*self._args)
            self._done.set()
        elif not checkpoint and self._done.is_set():
            return
        else:
            await self._done.wait()

    @property
    def done(self) -> bool:
        return bool(self._done.is_set())


_State = _Enum("_State", ["OK", "BROKEN", "CLOSED"])

# invariant
T_Stream = TypeVar("T_Stream", bound=Stream)


@final
class SSLStream(Stream, Generic[T_Stream]):
    r"""Encrypted communication using SSL/TLS.

    :class:`SSLStream` wraps an arbitrary :class:`~trio.abc.Stream`, and
    allows you to perform encrypted communication over it using the usual
    :class:`~trio.abc.Stream` interface. You pass regular data to
    :meth:`send_all`, then it encrypts it and sends the encrypted data on the
    underlying :class:`~trio.abc.Stream`; :meth:`receive_some` takes encrypted
    data out of the underlying :class:`~trio.abc.Stream` and decrypts it
    before returning it.

    You should read the standard library's :mod:`ssl` documentation carefully
    before attempting to use this class, and probably other general
    documentation on SSL/TLS as well. SSL/TLS is subtle and quick to
    anger. Really. I'm not kidding.

    Args:
      transport_stream (~trio.abc.Stream): The stream used to transport
          encrypted data. Required.

      ssl_context (~ssl.SSLContext): The :class:`~ssl.SSLContext` used for
          this connection. Required. Usually created by calling
          :func:`ssl.create_default_context`.

      server_hostname (str, bytes, or None): The name of the server being
          connected to. Used for `SNI
          <https://en.wikipedia.org/wiki/Server_Name_Indication>`__ and for
          validating the server's certificate (if hostname checking is
          enabled). This is effectively mandatory for clients, and actually
          mandatory if ``ssl_context.check_hostname`` is ``True``.

      server_side (bool): Whether this stream is acting as a client or
          server. Defaults to False, i.e. client mode.

      https_compatible (bool): There are two versions of SSL/TLS commonly
          encountered in the wild: the standard version, and the version used
          for HTTPS (HTTP-over-SSL/TLS).

          Standard-compliant SSL/TLS implementations always send a
          cryptographically signed ``close_notify`` message before closing the
          connection. This is important because if the underlying transport
          were simply closed, then there wouldn't be any way for the other
          side to know whether the connection was intentionally closed by the
          peer that they negotiated a cryptographic connection to, or by some
          `man-in-the-middle
          <https://en.wikipedia.org/wiki/Man-in-the-middle_attack>`__ attacker
          who can't manipulate the cryptographic stream, but can manipulate
          the transport layer (a so-called "truncation attack").

          However, this part of the standard is widely ignored by real-world
          HTTPS implementations, which means that if you want to interoperate
          with them, then you NEED to ignore it too.

          Fortunately this isn't as bad as it sounds, because the HTTP
          protocol already includes its own equivalent of ``close_notify``, so
          doing this again at the SSL/TLS level is redundant. But not all
          protocols do! Therefore, by default Trio implements the safer
          standard-compliant version (``https_compatible=False``). But if
          you're speaking HTTPS or some other protocol where
          ``close_notify``\s are commonly skipped, then you should set
          ``https_compatible=True``; with this setting, Trio will neither
          expect nor send ``close_notify`` messages.

          If you have code that was written to use :class:`ssl.SSLSocket` and
          now you're porting it to Trio, then it may be useful to know that a
          difference between :class:`SSLStream` and :class:`ssl.SSLSocket` is
          that :class:`~ssl.SSLSocket` implements the
          ``https_compatible=True`` behavior by default.

    Attributes:
      transport_stream (trio.abc.Stream): The underlying transport stream
          that was passed to ``__init__``. An example of when this would be
          useful is if you're using :class:`SSLStream` over a
          :class:`~trio.SocketStream` and want to call the
          :class:`~trio.SocketStream`'s :meth:`~trio.SocketStream.setsockopt`
          method.

    Internally, this class is implemented using an instance of
    :class:`ssl.SSLObject`, and all of :class:`~ssl.SSLObject`'s methods and
    attributes are re-exported as methods and attributes on this class.
    However, there is one difference: :class:`~ssl.SSLObject` has several
    methods that return information about the encrypted connection, like
    :meth:`~ssl.SSLSocket.cipher` or
    :meth:`~ssl.SSLSocket.selected_alpn_protocol`. If you call them before the
    handshake, when they can't possibly return useful data, then
    :class:`ssl.SSLObject` returns None, but :class:`trio.SSLStream`
    raises :exc:`NeedHandshakeError`.

    This also means that if you register a SNI callback using
    `~ssl.SSLContext.sni_callback`, then the first argument your callback
    receives will be a :class:`ssl.SSLObject`.

    """

    # Note: any new arguments here should likely also be added to
    # SSLListener.__init__, and maybe the open_ssl_over_tcp_* helpers.
    def __init__(
        self,
        transport_stream: T_Stream,
        ssl_context: _stdlib_ssl.SSLContext,
        *,
        server_hostname: str | bytes | None = None,
        server_side: bool = False,
        https_compatible: bool = False,
    ) -> None:
        self.transport_stream: T_Stream = transport_stream
        self._state = _State.OK
        self._https_compatible = https_compatible
        self._outgoing = _stdlib_ssl.MemoryBIO()
        self._delayed_outgoing: bytes | None = None
        self._incoming = _stdlib_ssl.MemoryBIO()
        self._ssl_object = ssl_context.wrap_bio(
            self._incoming,
            self._outgoing,
            server_side=server_side,
            server_hostname=server_hostname,
        )
        # Tracks whether we've already done the initial handshake
        self._handshook = _Once(self._do_handshake)

        # These are used to synchronize access to self.transport_stream
        self._inner_send_lock = _sync.StrictFIFOLock()
        self._inner_recv_count = 0
        self._inner_recv_lock = _sync.Lock()

        # These are used to make sure that our caller doesn't attempt to make
        # multiple concurrent calls to send_all/wait_send_all_might_not_block
        # or to receive_some.
        self._outer_send_conflict_detector = ConflictDetector(
            "another task is currently sending data on this SSLStream"
        )
        self._outer_recv_conflict_detector = ConflictDetector(
            "another task is currently receiving data on this SSLStream"
        )

        self._estimated_receive_size = STARTING_RECEIVE_SIZE

    _forwarded: ClassVar = {
        "context",
        "server_side",
        "server_hostname",
        "session",
        "session_reused",
        "getpeercert",
        "selected_npn_protocol",
        "cipher",
        "shared_ciphers",
        "compression",
        "pending",
        "get_channel_binding",
        "selected_alpn_protocol",
        "version",
    }

    _after_handshake: ClassVar = {
        "session_reused",
        "getpeercert",
        "selected_npn_protocol",
        "cipher",
        "shared_ciphers",
        "compression",
        "get_channel_binding",
        "selected_alpn_protocol",
        "version",
    }

    def __getattr__(self, name: str) -> Any:
        if name in self._forwarded:
            if name in self._after_handshake and not self._handshook.done:
                raise NeedHandshakeError(f"call do_handshake() before calling {name!r}")

            return getattr(self._ssl_object, name)
        else:
            raise AttributeError(name)

    def __setattr__(self, name: str, value: object) -> None:
        if name in self._forwarded:
            setattr(self._ssl_object, name, value)
        else:
            super().__setattr__(name, value)

    def __dir__(self) -> list[str]:
        return list(super().__dir__()) + list(self._forwarded)

    def _check_status(self) -> None:
        if self._state is _State.OK:
            return
        elif self._state is _State.BROKEN:
            raise trio.BrokenResourceError
        elif self._state is _State.CLOSED:
            raise trio.ClosedResourceError
        else:  # pragma: no cover
            raise AssertionError()

    # This is probably the single trickiest function in Trio. It has lots of
    # comments, though, just make sure to think carefully if you ever have to
    # touch it. The big comment at the top of this file will help explain
    # too.
    async def _retry(
        self,
        fn: Callable[..., T],
        *args: object,
        ignore_want_read: bool = False,
        is_handshake: bool = False,
    ) -> T | None:
        await trio.lowlevel.checkpoint_if_cancelled()
        yielded = False
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
            # come in and leapfrog us.

            # Call the SSLObject method, and get its result.
            #
            # NB: despite what the docs say, SSLWantWriteError can't
            # happen – "Writes to memory BIOs will always succeed if
            # memory is available: that is their size can grow
            # indefinitely."
            # https://wiki.openssl.org/index.php/Manual:BIO_s_mem(3)
            want_read = False
            ret = None
            try:
                ret = fn(*args)
            except _stdlib_ssl.SSLWantReadError:
                want_read = True
            except (_stdlib_ssl.SSLError, _stdlib_ssl.CertificateError) as exc:
                self._state = _State.BROKEN
                raise trio.BrokenResourceError from exc
            else:
                finished = True
            if ignore_want_read:
                want_read = False
                finished = True
            to_send = self._outgoing.read()

            # Some versions of SSL_do_handshake have a bug in how they handle
            # the TLS 1.3 handshake on the server side: after the handshake
            # finishes, they automatically send session tickets, even though
            # the client may not be expecting data to arrive at this point and
            # sending it could cause a deadlock or lost data. This applies at
            # least to OpenSSL 1.1.1c and earlier, and the OpenSSL devs
            # currently have no plans to fix it:
            #
            #   https://github.com/openssl/openssl/issues/7948
            #   https://github.com/openssl/openssl/issues/7967
            #
            # The correct behavior is to wait to send session tickets on the
            # first call to SSL_write. (This is what BoringSSL does.) So, we
            # use a heuristic to detect when OpenSSL has tried to send session
            # tickets, and we manually delay sending them until the
            # appropriate moment. For more discussion see:
            #
            #   https://github.com/python-trio/trio/issues/819#issuecomment-517529763
            if (
                is_handshake
                and not want_read
                and self._ssl_object.server_side
                and self._ssl_object.version() == "TLSv1.3"
            ):
                assert self._delayed_outgoing is None
                self._delayed_outgoing = to_send
                to_send = b""

            # Outputs from the above code block are:
            #
            # - to_send: bytestring; if non-empty then we need to send
            #   this data to make forward progress
            #
            # - want_read: True if we need to receive_some some data to make
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
            # - receive_some some data and put it into the incoming BIO
            #
            # Our strategy is: if there's data to send, send it;
            # *otherwise* if there's data to receive_some, receive_some it.
            #
            # If both need to happen, then we only send. Why? Well, we
            # know that *right now* we have to both send and receive_some
            # before the operation can complete. But as soon as we yield,
            # that information becomes potentially stale – e.g. while
            # we're sending, some other task might go and receive_some the
            # data we need and put it into the incoming BIO. And if it
            # does, then we *definitely don't* want to do a receive_some –
            # there might not be any more data coming, and we'd deadlock!
            # We could do something tricky to keep track of whether a
            # receive_some happens while we're sending, but the case where
            # we have to do both is very unusual (only during a
            # renegotiation), so it's better to keep things simple. So we
            # do just one potentially-blocking operation, then check again
            # for fresh information.
            #
            # And we prioritize sending over receiving because, if there
            # are multiple tasks that want to receive_some, then it
            # doesn't matter what order they go in. But if there are
            # multiple tasks that want to send, then they each have
            # different data, and the data needs to get put onto the wire
            # in the same order that it was retrieved from the outgoing
            # BIO. So if we have data to send, that *needs* to be the
            # *very* *next* *thing* we do, to make sure no-one else sneaks
            # in before us. Or if we can't send immediately because
            # someone else is, then we at least need to get in line
            # immediately.
            if to_send:
                # NOTE: This relies on the lock being strict FIFO fair!
                async with self._inner_send_lock:
                    yielded = True
                    try:
                        if self._delayed_outgoing is not None:
                            to_send = self._delayed_outgoing + to_send
                            self._delayed_outgoing = None
                        await self.transport_stream.send_all(to_send)
                    except:
                        # Some unknown amount of our data got sent, and we
                        # don't know how much. This stream is doomed.
                        self._state = _State.BROKEN
                        raise
            elif want_read:
                # It's possible that someone else is already blocked in
                # transport_stream.receive_some. If so then we want to
                # wait for them to finish, but we don't want to call
                # transport_stream.receive_some again ourselves; we just
                # want to loop around and check if their contribution
                # helped anything. So we make a note of how many times
                # some task has been through here before taking the lock,
                # and if it's changed by the time we get the lock, then we
                # skip calling transport_stream.receive_some and loop
                # around immediately.
                recv_count = self._inner_recv_count
                async with self._inner_recv_lock:
                    yielded = True
                    if recv_count == self._inner_recv_count:
                        data = await self.transport_stream.receive_some()
                        if not data:
                            self._incoming.write_eof()
                        else:
                            self._estimated_receive_size = max(
                                self._estimated_receive_size, len(data)
                            )
                            self._incoming.write(data)
                        self._inner_recv_count += 1
        if not yielded:
            await trio.lowlevel.cancel_shielded_checkpoint()
        return ret

    async def _do_handshake(self) -> None:
        try:
            await self._retry(self._ssl_object.do_handshake, is_handshake=True)
        except:
            self._state = _State.BROKEN
            raise

    async def do_handshake(self) -> None:
        """Ensure that the initial handshake has completed.

        The SSL protocol requires an initial handshake to exchange
        certificates, select cryptographic keys, and so forth, before any
        actual data can be sent or received. You don't have to call this
        method; if you don't, then :class:`SSLStream` will automatically
        perform the handshake as needed, the first time you try to send or
        receive data. But if you want to trigger it manually – for example,
        because you want to look at the peer's certificate before you start
        talking to them – then you can call this method.

        If the initial handshake is already in progress in another task, this
        waits for it to complete and then returns.

        If the initial handshake has already completed, this returns
        immediately without doing anything (except executing a checkpoint).

        .. warning:: If this method is cancelled, then it may leave the
           :class:`SSLStream` in an unusable state. If this happens then any
           future attempt to use the object will raise
           :exc:`trio.BrokenResourceError`.

        """
        self._check_status()
        await self._handshook.ensure(checkpoint=True)

    # Most things work if we don't explicitly force do_handshake to be called
    # before calling receive_some or send_all, because openssl will
    # automatically perform the handshake on the first SSL_{read,write}
    # call. BUT, allowing openssl to do this will disable Python's hostname
    # checking!!! See:
    #   https://bugs.python.org/issue30141
    # So we *definitely* have to make sure that do_handshake is called
    # before doing anything else.
    async def receive_some(self, max_bytes: int | None = None) -> bytes | bytearray:
        """Read some data from the underlying transport, decrypt it, and
        return it.

        See :meth:`trio.abc.ReceiveStream.receive_some` for details.

        .. warning:: If this method is cancelled while the initial handshake
           or a renegotiation are in progress, then it may leave the
           :class:`SSLStream` in an unusable state. If this happens then any
           future attempt to use the object will raise
           :exc:`trio.BrokenResourceError`.

        """
        with self._outer_recv_conflict_detector:
            self._check_status()
            try:
                await self._handshook.ensure(checkpoint=False)
            except trio.BrokenResourceError as exc:
                # For some reason, EOF before handshake sometimes raises
                # SSLSyscallError instead of SSLEOFError (e.g. on my linux
                # laptop, but not on appveyor). Thanks openssl.
                if self._https_compatible and (
                    isinstance(exc.__cause__, _stdlib_ssl.SSLSyscallError)
                    or _is_eof(exc.__cause__)
                ):
                    await trio.lowlevel.checkpoint()
                    return b""
                else:
                    raise
            if max_bytes is None:
                # If we somehow have more data already in our pending buffer
                # than the estimate receive size, bump up our size a bit for
                # this read only.
                max_bytes = max(self._estimated_receive_size, self._incoming.pending)
            else:
                max_bytes = _operator.index(max_bytes)
                if max_bytes < 1:
                    raise ValueError("max_bytes must be >= 1")
            try:
                received = await self._retry(self._ssl_object.read, max_bytes)
                assert received is not None
                return received
            except trio.BrokenResourceError as exc:
                # This isn't quite equivalent to just returning b"" in the
                # first place, because we still end up with self._state set to
                # BROKEN. But that's actually fine, because after getting an
                # EOF on TLS then the only thing you can do is close the
                # stream, and closing doesn't care about the state.

                if self._https_compatible and _is_eof(exc.__cause__):
                    await trio.lowlevel.checkpoint()
                    return b""
                else:
                    raise

    async def send_all(self, data: bytes | bytearray | memoryview) -> None:
        """Encrypt some data and then send it on the underlying transport.

        See :meth:`trio.abc.SendStream.send_all` for details.

        .. warning:: If this method is cancelled, then it may leave the
           :class:`SSLStream` in an unusable state. If this happens then any
           attempt to use the object will raise
           :exc:`trio.BrokenResourceError`.

        """
        with self._outer_send_conflict_detector:
            self._check_status()
            await self._handshook.ensure(checkpoint=False)
            # SSLObject interprets write(b"") as an EOF for some reason, which
            # is not what we want.
            if not data:
                await trio.lowlevel.checkpoint()
                return
            await self._retry(self._ssl_object.write, data)

    async def unwrap(self) -> tuple[Stream, bytes | bytearray]:
        """Cleanly close down the SSL/TLS encryption layer, allowing the
        underlying stream to be used for unencrypted communication.

        You almost certainly don't need this.

        Returns:
          A pair ``(transport_stream, trailing_bytes)``, where
          ``transport_stream`` is the underlying transport stream, and
          ``trailing_bytes`` is a byte string. Since :class:`SSLStream`
          doesn't necessarily know where the end of the encrypted data will
          be, it can happen that it accidentally reads too much from the
          underlying stream. ``trailing_bytes`` contains this extra data; you
          should process it as if it was returned from a call to
          ``transport_stream.receive_some(...)``.

        """
        with self._outer_recv_conflict_detector, self._outer_send_conflict_detector:
            self._check_status()
            await self._handshook.ensure(checkpoint=False)
            await self._retry(self._ssl_object.unwrap)
            transport_stream = self.transport_stream
            self._state = _State.CLOSED
            self.transport_stream = None  # type: ignore[assignment]  # State is CLOSED now, nothing should use
            return (transport_stream, self._incoming.read())

    async def aclose(self) -> None:
        """Gracefully shut down this connection, and close the underlying
        transport.

        If ``https_compatible`` is False (the default), then this attempts to
        first send a ``close_notify`` and then close the underlying stream by
        calling its :meth:`~trio.abc.AsyncResource.aclose` method.

        If ``https_compatible`` is set to True, then this simply closes the
        underlying stream and marks this stream as closed.

        """
        if self._state is _State.CLOSED:
            await trio.lowlevel.checkpoint()
            return
        if self._state is _State.BROKEN or self._https_compatible:
            self._state = _State.CLOSED
            await self.transport_stream.aclose()
            return
        try:
            # https_compatible=False, so we're in spec-compliant mode and have
            # to send close_notify so that the other side gets a cryptographic
            # assurance that we've called aclose. Of course, we can't do
            # anything cryptographic until after we've completed the
            # handshake:
            await self._handshook.ensure(checkpoint=False)
            # Then, we call SSL_shutdown *once*, because we want to send a
            # close_notify but *not* wait for the other side to send back a
            # response. In principle it would be more polite to wait for the
            # other side to reply with their own close_notify. However, if
            # they aren't paying attention (e.g., if they're just sending
            # data and not receiving) then we will never notice our
            # close_notify and we'll be waiting forever. Eventually we'll time
            # out (hopefully), but it's still kind of nasty. And we can't
            # require the other side to always be receiving, because (a)
            # backpressure is kind of important, and (b) I bet there are
            # broken TLS implementations out there that don't receive all the
            # time. (Like e.g. anyone using Python ssl in synchronous mode.)
            #
            # The send-then-immediately-close behavior is explicitly allowed
            # by the TLS specs, so we're ok on that.
            #
            # Subtlety: SSLObject.unwrap will immediately call it a second
            # time, and the second time will raise SSLWantReadError because
            # there hasn't been time for the other side to respond
            # yet. (Unless they spontaneously sent a close_notify before we
            # called this, and it's either already been processed or gets
            # pulled out of the buffer by Python's second call.) So the way to
            # do what we want is to ignore SSLWantReadError on this call.
            #
            # Also, because the other side might have already sent
            # close_notify and closed their connection then it's possible that
            # our attempt to send close_notify will raise
            # BrokenResourceError. This is totally legal, and in fact can happen
            # with two well-behaved Trio programs talking to each other, so we
            # don't want to raise an error. So we suppress BrokenResourceError
            # here. (This is safe, because literally the only thing this call
            # to _retry will do is send the close_notify alert, so that's
            # surely where the error comes from.)
            #
            # FYI in some cases this could also raise SSLSyscallError which I
            # think is because SSL_shutdown is terrible. (Check out that note
            # at the bottom of the man page saying that it sometimes gets
            # raised spuriously.) I haven't seen this since we switched to
            # immediately closing the socket, and I don't know exactly what
            # conditions cause it and how to respond, so for now we're just
            # letting that happen. But if you start seeing it, then hopefully
            # this will give you a little head start on tracking it down,
            # because whoa did this puzzle us at the 2017 PyCon sprints.
            #
            # Also, if someone else is blocked in send/receive, then we aren't
            # going to be able to do a clean shutdown. If that happens, we'll
            # just do an unclean shutdown.
            try:
                await self._retry(self._ssl_object.unwrap, ignore_want_read=True)
            except (trio.BrokenResourceError, trio.BusyResourceError):
                pass
        except:
            # Failure! Kill the stream and move on.
            await aclose_forcefully(self.transport_stream)
            raise
        else:
            # Success! Gracefully close the underlying stream.
            await self.transport_stream.aclose()
        finally:
            self._state = _State.CLOSED

    async def wait_send_all_might_not_block(self) -> None:
        """See :meth:`trio.abc.SendStream.wait_send_all_might_not_block`."""
        # This method's implementation is deceptively simple.
        #
        # First, we take the outer send lock, because of Trio's standard
        # semantics that wait_send_all_might_not_block and send_all
        # conflict.
        with self._outer_send_conflict_detector:
            self._check_status()
            # Then we take the inner send lock. We know that no other tasks
            # are calling self.send_all or self.wait_send_all_might_not_block,
            # because we have the outer_send_lock. But! There might be another
            # task calling self.receive_some -> transport_stream.send_all, in
            # which case if we were to call
            # transport_stream.wait_send_all_might_not_block directly we'd
            # have two tasks doing write-related operations on
            # transport_stream simultaneously, which is not allowed. We
            # *don't* want to raise this conflict to our caller, because it's
            # purely an internal affair – all they did was call
            # wait_send_all_might_not_block and receive_some at the same time,
            # which is totally valid. And waiting for the lock is OK, because
            # a call to send_all certainly wouldn't complete while the other
            # task holds the lock.
            async with self._inner_send_lock:
                # Now we have the lock, which creates another potential
                # problem: what if a call to self.receive_some attempts to do
                # transport_stream.send_all now? It'll have to wait for us to
                # finish! But that's OK, because we release the lock as soon
                # as the underlying stream becomes writable, and the
                # self.receive_some call wasn't going to make any progress
                # until then anyway.
                #
                # Of course, this does mean we might return *before* the
                # stream is logically writable, because immediately after we
                # return self.receive_some might write some data and make it
                # non-writable again. But that's OK too,
                # wait_send_all_might_not_block only guarantees that it
                # doesn't return late.
                await self.transport_stream.wait_send_all_might_not_block()


@final
class SSLListener(Listener[SSLStream[T_Stream]]):
    """A :class:`~trio.abc.Listener` for SSL/TLS-encrypted servers.

    :class:`SSLListener` wraps around another Listener, and converts
    all incoming connections to encrypted connections by wrapping them
    in a :class:`SSLStream`.

    Args:
      transport_listener (~trio.abc.Listener): The listener whose incoming
          connections will be wrapped in :class:`SSLStream`.

      ssl_context (~ssl.SSLContext): The :class:`~ssl.SSLContext` that will be
          used for incoming connections.

      https_compatible (bool): Passed on to :class:`SSLStream`.

    Attributes:
      transport_listener (trio.abc.Listener): The underlying listener that was
          passed to ``__init__``.

    """

    def __init__(
        self,
        transport_listener: Listener[T_Stream],
        ssl_context: _stdlib_ssl.SSLContext,
        *,
        https_compatible: bool = False,
    ) -> None:
        self.transport_listener = transport_listener
        self._ssl_context = ssl_context
        self._https_compatible = https_compatible

    async def accept(self) -> SSLStream[T_Stream]:
        """Accept the next connection and wrap it in an :class:`SSLStream`.

        See :meth:`trio.abc.Listener.accept` for details.

        """
        transport_stream = await self.transport_listener.accept()
        return SSLStream(
            transport_stream,
            self._ssl_context,
            server_side=True,
            https_compatible=self._https_compatible,
        )

    async def aclose(self) -> None:
        """Close the transport listener."""
        await self.transport_listener.aclose()
