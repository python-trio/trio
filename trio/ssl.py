# Use SSLObject to make a generic wrapper around Stream

# SSL shutdown:
# - call unwrap() on the SSLSocket/SSLObject
# - this sends the "all done here" SSL message
# - but in many practical applications this is neither sent nor checked for,
#   e.g. HTTPS usually ignores it:
#   https://security.stackexchange.com/questions/82028/ssl-tls-is-a-server-always-required-to-respond-to-a-close-notify
#   BUT it is important in some cases, so should be possible to handle
#   properly.
#
# I think the answer is: close is synchronous, and the TLS Stream also has an
# async def unwrap() which sends the close_notify message.
# Possibly we should also default suppress_ragged_eofs to False, unlike the
# stdlib? not sure.

# XX how closely should we match the stdlib API?
# - maybe suppress_ragged_eofs=False is a better default?
# - maybe check crypto folks for advice?
# - this is also interesting: https://bugs.python.org/issue8108#msg102867

# Definitely keep an eye on Cory's TLS API ideas on security-sig etc.

# XX document behavior on cancellation/error (i.e.: all is lost abandon
# stream)
# docs will need to make very clear that this is different from all the other
# cancellations in core trio

# XX should we make server_hostname required (so you set it to None to disable
# hostname checking?) whenever ctx.check_hostname is True? -- ah, actually ssl
# already does this for us :-)

import ssl as _stdlib_ssl

from . import _core
from . import _streams
from . import _sync

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


# Instead of _Once, have an ensure_n_times, and use it for recv? or maybe
# just ensure_increment, since we know we don't yield between the ssl call and
# the ensure call? (assume we don't try to both send and receive together)

# maybe _NonblockingMutex should be public as like UnLock (= unnecessary lock)
# also useful for things like documenting that we do all our interaction with
# the ssl_object without yielding? (but lighter weight than assert_no_yields?)
# though the critical thing is not just that we don't yield but how exactly we
# do eventually yield so eh.

class _NonblockingMutex:
    def __init__(self, errmsg):
        self._errmsg = errmsg
        self._held = False

    def __enter__(self):
        if self._held:
            raise RuntimeError(errmsg)
        else:
            self._held = True

    def __exit__(self, *args):
        self._held = False


class SSLStream(_streams.Stream):
    def __init__(
            self, wrapped_stream, sslcontext, *, bufsize=32 * 1024, **kwargs):
        self.wrapped_stream = wrapped_stream
        self._bufsize = bufsize
        self._outgoing = _stdlib_ssl.MemoryBIO()
        self._incoming = _stdlib_ssl.MemoryBIO()
        self._ssl_object = sslcontext.wrap_bio(
            self._incoming, self._outgoing, **kwargs)
        self._inner_send_lock = _sync.Lock()
        self._inner_recv_count = 0
        self._inner_recv_lock = _sync.Lock()
        self._handshook = _Once(self._do_handshake)

        self._outer_send_lock = _NonblockingMutex(
            "another task is currently sending data on this SSLStream")
        self._outer_recv_lock = _NonblockingMutex(
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

    can_send_eof = False

    async def send_eof(self):
        raise RuntimeError("the TLS protocol does not support send_eof")

    async def wait_writable(self):
        await self.wrapped_stream.wait_writable()

    async def _retry(self, fn, *args):
        await _core.yield_if_cancelled()
        yielded = False
        try:
            finished = False
            while not finished:
                want_read = False
                try:
                    ret = fn(*args)
                except _stdlib_ssl.SSLWantReadError:
                    want_read = True
                # SSLWantWriteError can't happen – "Writes to memory BIOs will
                # always succeed if memory is available: that is their size
                # can grow indefinitely."
                # https://wiki.openssl.org/index.php/Manual:BIO_s_mem(3)
                else:
                    finished = True
                recv_count = self._inner_recv_count
                if self._outgoing.pending:
                    # We pull the data out eagerly, so that in the common case
                    # of simultaneous sendall() and recv(), sendall() doesn't
                    # leave data in self._outgoing over a schedule point and
                    # trick recv() into thinking that it has data to
                    # send. This relies on the fairness of send_lock for
                    # correctness, to make sure that 'data' chunks don't get
                    # re-ordered.
                    print("sending")
                    data = self._outgoing.read()
                    async with self._inner_send_lock:
                        await self.wrapped_stream.sendall(data)
                        yielded = True
                    #continue
                if want_read:
                    print("receiving")
                    if recv_count == self._inner_recv_count:
                        async with self._inner_recv_lock:
                            if recv_count == self._inner_recv_count:
                                data = await self.wrapped_stream.recv(self._bufsize)
                                yielded = True
                                if not data:
                                    self._incoming.write_eof()
                                else:
                                    self._incoming.write(data)
                                self._inner_recv_count += 1

            return ret
        finally:
            if not yielded:
                await _core.yield_briefly_no_cancel()

    async def _retry_recv(self, fn, *args):
        await _core.yield_if_cancelled()
        yielded = False
        try:
            finished = False
            while not finished:
                want_read = False
                try:
                    ret = fn(*args)
                except _stdlib_ssl.SSLWantReadError:
                    want_read = True
                # SSLWantWriteError can't happen – "Writes to memory BIOs will
                # always succeed if memory is available: that is their size
                # can grow indefinitely."
                # https://wiki.openssl.org/index.php/Manual:BIO_s_mem(3)
                else:
                    finished = True
                recv_count = self._inner_recv_count
                if self._outgoing.pending:
                    # We pull the data out eagerly, so that in the common case
                    # of simultaneous sendall() and recv(), sendall() doesn't
                    # leave data in self._outgoing over a schedule point and
                    # trick recv() into thinking that it has data to
                    # send. This relies on the fairness of send_lock for
                    # correctness, to make sure that 'data' chunks don't get
                    # re-ordered.
                    print("recv sending", self._inner_send_lock.locked())
                    data = self._outgoing.read()
                    async with self._inner_send_lock:
                        await self.wrapped_stream.sendall(data)
                        yielded = True
                if want_read:
                    print("recv reading", self._inner_recv_lock.locked())
                    if recv_count == self._inner_recv_count:
                        async with self._inner_recv_lock:
                            if recv_count == self._inner_recv_count:
                                data = await self.wrapped_stream.recv(self._bufsize)
                                yielded = True
                                if not data:
                                    self._incoming.write_eof()
                                else:
                                    self._incoming.write(data)
                                self._inner_recv_count += 1

            return ret
        finally:
            if not yielded:
                await _core.yield_briefly_no_cancel()

    async def _retry_sendall(self, fn, *args):
        await _core.yield_if_cancelled()
        yielded = False
        try:
            finished = False
            while not finished:
                want_read = False
                try:
                    ret = fn(*args)
                except _stdlib_ssl.SSLWantReadError:
                    want_read = True
                # SSLWantWriteError can't happen – "Writes to memory BIOs will
                # always succeed if memory is available: that is their size
                # can grow indefinitely."
                # https://wiki.openssl.org/index.php/Manual:BIO_s_mem(3)
                else:
                    finished = True
                recv_count = self._inner_recv_count
                if self._outgoing.pending:
                    # We pull the data out eagerly, so that in the common case
                    # of simultaneous sendall() and recv(), sendall() doesn't
                    # leave data in self._outgoing over a schedule point and
                    # trick recv() into thinking that it has data to
                    # send. This relies on the fairness of send_lock for
                    # correctness, to make sure that 'data' chunks don't get
                    # re-ordered.
                    print("sendall sending", self._inner_send_lock.locked())
                    data = self._outgoing.read()
                    async with self._inner_send_lock:
                        await self.wrapped_stream.sendall(data)
                        yielded = True
                if want_read:
                    print("sendall reading", self._inner_recv_lock.locked())
                    print(recv_count, self._inner_recv_count)
                    if recv_count == self._inner_recv_count:
                        async with self._inner_recv_lock:
                            print(recv_count, self._inner_recv_count)
                            if recv_count == self._inner_recv_count:
                                data = await self.wrapped_stream.recv(self._bufsize)
                                yielded = True
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

    async def do_handshake(self):
        await self._handshook.ensure(checkpoint=True)

    # Most things work if we don't explicitly force do_handshake to be called
    # before calling recv or sendall, because openssl will automatically
    # perform the handshake on the first SSL_{read,write} call. BUT, allowing
    # openssl to do this will disable Python's hostname checking! See:
    #   https://bugs.python.org/issue30141
    # So we *definitely* have to make sure that do_handshake is called
    # before doing anything else.
    async def recv(self, bufsize):
        with self._outer_recv_lock:
            await self._handshook.ensure(checkpoint=False)
            return await self._retry_recv(self._ssl_object.read, bufsize)

    async def sendall(self, data):
        with self._outer_send_lock:
            await self._handshook.ensure(checkpoint=False)
            return await self._retry_sendall(self._ssl_object.write, data)

    async def unwrap(self):
        with self._outer_recv_lock, self._outer_send_lock:
            await self._handshook.ensure(checkpoint=False)
            await self._retry(self._ssl_object.unwrap)
            return (self.wrapped_stream, self._incoming.read())

    def forceful_close(self):
        self.wrapped_stream.forceful_close()

    async def graceful_close(self):
        try:
            await self.unwrap()
            await self.wrapped_stream.graceful_close()
        except:
            self.forceful_close()
            raise
