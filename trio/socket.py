from functools import wraps as _wraps, partial as _partial
import socket as _stdlib_socket
import sys as _sys

from . import _core
from ._threads import run_in_worker_thread as _run_in_worker_thread
from ._streams import Stream as _Stream

__all__ = []

if _sys.platform == "darwin":
    TCP_NOTSENT_LOWAT = 0x201
elif _sys.platform == "linux":
    TCP_NOTSENT_LOWAT = 25

def _reexport(name):
    globals()[name] = getattr(_stdlib_socket, name)
    __all__.append(name)

for _name in _stdlib_socket.__dict__.keys():
    if _name == _name.upper():
        _reexport(_name)
for _name in [
        "gaierror", "herror", "getprotobyname", "getservbyname",
        "getservbyport", "ntohs", "htonl", "htons", "inet_aton", "inet_ntoa",
        "inet_pton", "inet_ntop", "sethostname", "if_nameindex",
        "if_nametoindex", "if_indextoname",
        ]:
    if hasattr(_stdlib_socket, _name):
        _reexport(_name)

def from_stdlib_socket(sock):
    if type(sock) is not _stdlib_socket.socket:
        # For example, ssl.SSLSocket subclasses socket.socket, but we
        # certainly don't want to blindly wrap one of those.
        raise TypeError(
            "expected object of type 'socket.socket', not '{}"
            .format(type(sock).__name__))
    return SocketType(sock)
__all__.append("from_stdlib_socket")

@_wraps(_stdlib_socket.fromfd, assigned=(), updated=())
def fromfd(*args, **kwargs):
    return from_stdlib_socket(_stdlib_socket.fromfd(*args, **kwargs))
__all__.append("fromfd")

if hasattr(_stdlib_socket, "fromshare"):
    @_wraps(_stdlib_socket.fromshare, assigned=(), updated=())
    def fromshare(*args, **kwargs):
        return from_stdlib_socket(_stdlib_socket.fromshare(*args, **kwargs))
    __all__.append("fromshare")

@_wraps(_stdlib_socket.socketpair, assigned=(), updated=())
def socketpair(*args, **kwargs):
    return tuple(
        from_stdlib_socket(s)
        for s in _stdlib_socket.socketpair(*args, **kwargs))
__all__.append("socketpair")

@_wraps(_stdlib_socket.socket, assigned=(), updated=())
def socket(*args, **kwargs):
    return from_stdlib_socket(_stdlib_socket.socket(*args, **kwargs))
__all__.append("socket")

_NUMERIC_ONLY = _stdlib_socket.AI_NUMERICHOST
if hasattr(_stdlib_socket, "AI_NUMERICSERV"):
    _NUMERIC_ONLY |= _stdlib_socket.AI_NUMERICSERV

async def _getaddrinfo_impl(host, port, family=0, type=0, proto=0, flags=0,
                            *, must_yield):
    try:
        info =_stdlib_socket.getaddrinfo(
            host, port, family, type, proto, flags | _NUMERIC_ONLY)
    except _stdlib_socket.gaierror:
        return await _run_in_worker_thread(
            _stdlib_socket.getaddrinfo,
            host, port, family, type, proto, flags,
            cancellable=True)
    else:
        if must_yield:
            await _core.yield_briefly()
        return info

@_wraps(_stdlib_socket.getaddrinfo, assigned=(), updated=())
async def getaddrinfo(*args, **kwargs):
    return await _getaddrinfo_impl(*args, **kwargs, must_yield=False)

__all__.append("getaddrinfo")

for _name in [
        "getfqdn", "getnameinfo",
        # obsolete gethostbyname etc. intentionally omitted
]:
    _fn = getattr(_stdlib_socket, _name)
    @_wraps(_fn, assigned=("__name__", "__doc__"))
    async def _wrapper(*args, **kwargs):
        return await _run_in_worker_thread(
            _partial(fn, *args, **kwargs), cancellable=True)

if hasattr(_core, "wait_socket_readable"):
    _wait_readable = _core.wait_socket_readable
    _wait_writable = _core.wait_socket_writable
else:
    _wait_readable = _core.wait_readable
    _wait_writable = _core.wait_writable

class SocketType(_Stream):
    def __init__(self, sock):
        self._sock = sock
        self._sock.setblocking(False)
        try:
            self.setsockopt(IPPROTO_TCP, TCP_NODELAY, True)
        except OSError:
            pass
        try:
            # 16 KiB is somewhat arbitrary and could possibly do with some
            # tuning. (Apple is also setting this by default in CFNetwork
            # apparently -- I'm curious what value they're using, though I
            # couldn't find it online trivially.)
            self.setsockopt(IPPROTO_TCP, TCP_NOTSENT_LOWAT, 2 ** 14)
        except (NameError, OSError):
            pass
        if self._sock.family == AF_INET6:
            self.setsockopt(IPPROTO_IPV6, IPV6_V6ONLY, True)

    ################################################################
    # Simple + portable methods and attributes
    ################################################################

    # for _name in [
    #         ]:
    #     _meth = getattr(_stdlib_socket.socket, _name)
    #     @_wraps(_meth, assigned=("__name__", "__doc__"), updated=())
    #     def _wrapped(self, *args, **kwargs):
    #         return getattr(self._sock, _meth)(*args, **kwargs)
    #     locals()[_meth] = _wrapped
    # del _name, _meth, _wrapped

    _forward = {
        "__enter__", "__exit__", "close", "detach", "get_inheritable",
        "set_inheritable", "fileno", "getpeername", "getsockname",
        "getsockopt", "setsockopt", "listen", "shutdown",
    }
    def __getattr__(self, name):
        if name in self._forward:
            return getattr(self._sock, name)
        raise AttributeError(name)

    # Need an explicit method to make the Stream abc happy:
    def close(self):
        self._sock.close()

    @property
    def family(self):
        return self._sock.family

    @property
    def type(self):
        return self._sock.type

    @property
    def proto(self):
        return self._sock.proto

    def __repr__(self):
        return repr(self._sock).replace("socket.socket", "trio.socket.socket")

    def dup(self):
        return SocketType(self._sock.dup())

    def bind(self, address):
        self._check_address(address, require_resolved=True)
        return self._sock.bind(address)

    def can_send_eof(self):
        return True

    def send_eof(self):
        self.shutdown(SHUT_WR)

    ################################################################
    # Address handling
    ################################################################

    # For socket operations that take addresses, Python helpfully accepts
    # addresses containing names, and implicitly resolves them. This is no
    # good, because the implicit resolution is blocking. We require that all
    # such addresses be "pre-resolved" meaning:
    #
    # - For AF_INET or AF_INET6, they must contain only numeric elements. We
    #   check using getaddrinfo with AI_NUMERIC{HOST,SERV} flags set.
    # - For other families, we cross our fingers and hope the user knows what
    #   they're doing.
    #
    # And we provide two convenience functions to do this "pre-resolution",
    # which attempt to match what Python does.

    def _check_address(self, address, *, require_resolved):
        if self._sock.family == AF_INET:
            if not isinstance(address, tuple) or not len(address) == 2:
                raise ValueError("address should be a (host, port) tuple")
        elif self._sock.family == AF_INET6:
            if not isinstance(address, tuple) or not 2 <= len(address) <= 4:
                raise ValueError(
                    "address should be a (host, port, [flowinfo, [scopeid]]) "
                    "tuple")
        else:
            return
        if require_resolved:  # for AF_INET{,6} only
            try:
                _stdlib_socket.getaddrinfo(
                    address[0], address[1],
                    self._sock.family, self._sock.type, self._sock.proto,
                    flags=_NUMERIC_ONLY)
            except gaierror:
                raise ValueError(
                    "expected an already-resolved numeric address, not {}"
                    .format(address))

    # Take an address in Python's representation, and returns a new address in
    # the same representation, but with names resolved to numbers,
    # etc.
    async def _resolve_address(self, address, flags):
        self._check_address(address, require_resolved=False)
        if self._sock.family not in (AF_INET, AF_INET6):
            await _core.yield_briefly()
            return address
        flags |= AI_ADDRCONFIG
        if self._sock.family == AF_INET6:
            if not self._sock.getsockopt(IPPROTO_IPV6, IPV6_V6ONLY):
                flags |= AI_V4MAPPED
        gai_res = await getaddrinfo(
            address[0], address[1],
            self._sock.family, self._sock.type, self._sock.proto, flags)
        if not gai_res:
            raise OSError("getaddrinfo returned an empty list")
        normed, *_ = gai_res
        # The above ignored any flowid and scopeid in the passed-in address,
        # so restore them if present:
        if self._sock.family == AF_INET6:
            normed = list(normed)
            assert len(normed) == 4
            if len(address) >= 3:
                normed[2] = address[2]
            if len(address) >= 4:
                normed[3] = address[3]
            normed = tuple(normed)
        # Should never fail:
        self._check_address(address, require_resolved=True)
        return normed

    # Returns something appropriate to pass to bind()
    async def resolve_local_address(self, address):
        return await self._resolve_address(address, AI_PASSIVE)

    # Returns something appropriate to pass to connect()/sendto()/sendmsg()
    async def resolve_remote_address(self, address):
        return await self._resolve_address(address, 0)

    async def wait_maybe_writable(self):
        await _wait_writable(self._sock)

    async def _nonblocking_helper(self, fn, args, kwargs, wait_fn):
        # We have to reconcile two conflicting goals:
        # - We want to make it look like we always blocked in doing these
        #   operations. The obvious way is to always do an IO wait before
        #   calling the function.
        # - But, we also want to provide the correct semantics, and part
        #   of that means giving correct errors. So, for example, if you
        #   haven't called .listen(), then .accept() raises an error
        #   immediately. But in this same circumstance, then on MacOS, the
        #   socket does not register as readable. So if we block waiting
        #   for read *before* we call accept, then we'll be waiting
        #   forever instead of properly raising an error. (On Linux,
        #   interestingly, AFAICT a socket that can't possible read/write
        #   *does* count as readable/writable for select() purposes. But
        #   not on MacOS.)
        #
        # So, we have to call the function once, with the appropriate
        # cancellation/yielding sandwich if it succeeds, and if it gives
        # BlockingIOError *then* we fall back to IO wait.
        #
        # XX think if this can be combined with the similar logic for IOCP
        # submission...
        await _core.yield_if_cancelled()
        try:
            return fn(self._sock, *args, **kwargs)
        except BlockingIOError:
            pass
        finally:
            await _core.yield_briefly_no_cancel()
        # First attempt raised BlockingIOError:
        while True:
            await wait_fn(self._sock)
            try:
                return fn(self._sock, *args, **kwargs)
            except BlockingIOError:
                pass

    def _make_simple_wrapper(fn, wait_fn):
        @_wraps(fn, assigned=("__name__", "__doc__"), updated=())
        async def wrapper(self, *args, **kwargs):
            return await self._nonblocking_helper(fn, args, kwargs, wait_fn)
        return wrapper

    ################################################################
    # accept
    ################################################################

    accept = _make_simple_wrapper(
        _stdlib_socket.socket.accept, _wait_readable)

    ################################################################
    # connect
    ################################################################

    async def connect(self, address):
        """Connect the socket to a remote address.

        Unlike the stdlib ``connect``, this method requires a pre-resolved
        address. See :meth:`resolve_remote_address`.

        """
        self._check_address(address, require_resolved=True)
        # nonblocking connect is weird -- you call it to start things
        # off, then the socket becomes writable as a completion
        # notification. This means it isn't really cancellable...
        await _core.yield_if_cancelled()
        try:
            # For some reason, PEP 475 left InterruptedError as a
            # possible error for non-blocking connect
            # (specifically). But as far as I know, EINTR always means
            # you need to redo the call (with the extremely special
            # exception of close() on Linux, but that's unrelated, and
            # POSIX is cranky at them about it). If the kernel wanted
            # to signal that the connect really was in progress then
            # it'd have used EINPROGRESS. So we retry:
            while True:
                try:
                    return self._sock.connect(address)
                except InterruptedError:
                    pass
        except BlockingIOError:
            pass
        finally:
            # Either it raised a (real) error, or completed
            # instantly. Yield and let it exit.
            await _core.yield_briefly_no_cancel()
        # It raised BlockingIOError, meaning that it's started the
        # connection attempt. We wait for it to complete:
        try:
            await _wait_writable(self._sock)
        except _core.Cancelled:
            # We can't really cancel a connect, and the socket is in an
            # indeterminate state. Better to close it so we don't get
            # confused.
            self._sock.close()
            raise
        # Okay, the connect finished, but it might have failed:
        err = self._sock.getsockopt(SOL_SOCKET, SO_ERROR)
        if err != 0:
            raise OSError(err, "Error in connect: " + os.strerror(err))

    ################################################################
    # recv
    ################################################################

    recv = _make_simple_wrapper(
        _stdlib_socket.socket.recv, _wait_readable)

    ################################################################
    # recv_into
    ################################################################

    recv_into = _make_simple_wrapper(
        _stdlib_socket.socket.recv_into, _wait_readable)

    ################################################################
    # recvfrom
    ################################################################

    recvfrom = _make_simple_wrapper(
        _stdlib_socket.socket.recvfrom, _wait_readable)

    ################################################################
    # recvfrom_into
    ################################################################

    recvfrom_into = _make_simple_wrapper(
        _stdlib_socket.socket.recvfrom_into, _wait_readable)

    ################################################################
    # recvmsg
    ################################################################

    if hasattr(_stdlib_socket.socket, "recvmsg"):
        recvmsg = _make_simple_wrapper(
            _stdlib_socket.socket.recvmsg, _wait_readable)

    ################################################################
    # recvmsg_into
    ################################################################

    if hasattr(_stdlib_socket.socket, "recvmsg_into"):
        recvmsg_into = _make_simple_wrapper(
            _stdlib_socket.socket.recvmsg_into, _wait_readable)

    ################################################################
    # send
    ################################################################

    send = _make_simple_wrapper(
        _stdlib_socket.socket.send, _wait_writable)

    ################################################################
    # sendto
    ################################################################

    @_wraps(_stdlib_socket.socket.sendto, assigned=(), updated=())
    async def sendto(*args):
        # args is: data[, flags], address)
        # and kwargs are not accepted
        self._check_address(args[-1], require_resolved=True)
        return await self._nonblocking_helper(
            _stdlib_socket.socket.sendto, args, {}, _wait_writable)

    ################################################################
    # sendmsg
    ################################################################

    if hasattr(_stdlib_socket.socket, "sendmsg"):
        @_wraps(_stdlib_socket.socket.sendmsg, assigned=(), updated=())
        async def sendmsg(*args):
            # args is: buffers[, ancdata[, flags[, address]]]
            # and kwargs are not accepted
            if len(args) == 4 and args[-1] is not None:
                self._check_address(args[-1], require_resolved=True)
            return await self._nonblocking_helper(
                _stdlib_socket.socket.sendmsg, args, {}, _wait_writable)

        sendmsg.__doc__ = """See :meth:`socket.socket.sendmsg`.

        Unlike the stdlib ``sendmsg``, this method requires that if an address
        is given, it must be pre-resolved. See :meth:`resolve_remote_address`.
        """

    ################################################################
    # sendall
    ################################################################

    async def sendall(self, data, flags=0):
        """Send all the data to the socket.

        Accepts the same flags as :meth:`send`.

        If an error occurs or the operation is cancelled, then the resulting
        exception will have a ``.partial_result`` attribute with a
        ``.bytes_sent`` attribute containing the number of bytes sent.

        """
        with memoryview(data) as data:
            total_sent = 0
            try:
                while data:
                    sent = await self.send(data, flags)
                    total_sent += sent
                    data = data[sent:]
            except BaseException as exc:
                pr = _core.PartialResult(bytes_sent=total_sent)
                exc.partial_result = pr
                raise

    ################################################################
    # sendfile
    ################################################################

    async def sendfile(self, file, offset=0, count=None):
        "Not implemented yet"
        XX

    # Intentionally omitted:
    #   makefile
    #   setblocking
    #   settimeout
    #   timeout

__all__.append("SocketType")


# Copied from socket.create_connection and slightly tweaked.
#
# So this is a derivative work licensed under the PSF License, which requires
# the following notice:
#
#     Copyright © 2001-2017 Python Software Foundation; All Rights Reserved
#
# XX shouldn't this use AI_ADDRCONFIG? and ideally happy eyeballs...
#   actually it looks like V4MAPPED | ADDRCONFIG is the default on Linux, but
#   not on other systems. (V4MAPPED is irrelevant here b/c it's a no-op unless
#   family=AF_INET6)
# XX possibly we should just throw it out and replace with whatever API we
# like better :-) maybe an easy TLS option? AF_UNIX equivalent?
async def create_connection(address, source_address=None):
    host, port = address
    err = None
    for res in await _getaddrinfo_impl(
            host, port, 0, SOCK_STREAM, must_yield=False):
        af, socktype, proto, canonname, sa = res
        sock = None
        try:
            sock = socket(af, socktype, proto)
            if source_address:
                sock.bind(source_address)
            await sock.connect(sa)
            return sock
        except OSError as _:
            err = _
            if sock is not None:
                sock.close()
    if err is not None:
        raise err
    else:
        raise OSError("getaddrinfo returned an empty list")
__all__.append("create_connection")
