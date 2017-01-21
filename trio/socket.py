from functool import wraps as _wraps, partial as _partial
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
    _reexport(_name)

def from_stdlib_socket(sock):
    if type(sock) is not stdlib_socket.socket:
        # For example, ssl.SSLSocket subclasses socket.socket, but we
        # certainly don't want to blindly wrap one of those.
        raise TypeError(
            "expected object of type 'socket.socket', not '{}"
            .format(type(sock).__name__))
    return SocketType(sock)
__all__.append("from_stdlib_socket")

@_wraps(_stdlib_socket.fromfd)
def fromfd(*args, **kwargs):
    return from_stdlib_socket(_stdlib_socket.fromfd(*args, **kwargs))
__all__.append("fromfd")

@_wraps(_stdlib_socket.fromshare)
def fromshare(*args, **kwargs):
    return from_stdlib_socket(_stdlib_socket.fromshare(*args, **kwargs))
__all__.append("fromshare")

@_wraps(_stdlib_socket.socketpair)
def socketpair(*args, **kwargs):
    return tuple(
        from_stdlib_socket(s)
        for s in _stdlib_socket.socketpair(*args, **kwargs))
__all__.append("socketpair")

@_wraps(_stdlib_socket.socket)
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

@_wraps(_stdlib_socket.getaddrinfo)
async def getaddrinfo(*args, **kwargs):
    return await _getaddrinfo_impl(*args, **kwargs, must_yield=False)

__all__.append("getaddrinfo")

for _name in [
        "getfqdn", "getnameinfo",
        # obsolete gethostbyname etc. intentionally omitted
]:
    _fn = getattr(_stdlib_socket, _name)
    @_wraps(fn)
    async def _wrapper(*args, **kwargs):
        return await _run_in_worker_thread(
            _partial(fn, *args, **kwargs), cancellable=True)


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

    for _name in [
            "__enter__", "__exit__", "close", "detach", "get_inheritable",
            "set_inheritable", "fileno", "getpeername", "getsockname",
            "getsockopt", "setsockopt", "listen", "shutdown",
            ]:
        _meth = getattr(_stdlib_socket.SocketType, _name)
        @_wraps(_meth)
        def _wrapped(self, *args, **kwargs):
            return getattr(self._sock, _meth)(*args, **kwargs)
        locals()[_meth] = wrapped
    del _name, _meth, _wrapped

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

    async def bind(self, address):
        # calls getaddrinfo so can't be sync
        # XX probably there is a better way to do this...
        await _run_in_worker_thread(self.bind, address)

    if hasattr(_core, "current_iocp"):
        # Windows
        async def accept(self):
            new_sock = socket(self.family, self.type, self.proto)
            # XX hack: we need to allocate a buffer that's at least
            #   2 * (sizeof(sockaddr_$PROTO) + 16)
            # I think there's a proper way to figure out
            # sizeof(sockaddr_$PROTO) using getsockopt(SOL_SOCKET,
            # SO_PROTOCOL_INFO), but this is a huge pain. But I bet there
            # aren't any protocols that need >128 bytes for an address.
            ASSUMED_SOCKADDR_SIZE = 128
            buf = bytearray(2 * (ASSUMED_SOCKADDR_SIZE + 16))
            await _core.AcceptEx(
                self.fileno(), new_sock.fileno(), buf, 0,
                ASSUMED_SOCKADDR_SIZE + 16, ASSUMED_SOCKADDR_SIZE + 16)
            # Magic thing we have to call to finish making the socket ready:
            SO_UPDATE_ACCEPT_CONTEXT = 0x700B
            new_socket.setsockopt(
                SOL_SOCKET, SO_UPDATE_ACCEPT_CONTEXT, self.fileno())
            # What MS wants us to do now is to use GetAcceptExSockaddrs to
            # parse out the local and remote sockaddr from the buffer, and
            # then convert those into something useful somehow. But this
            # sounds like a lot of work, so we just call getpeername()
            # instead:
            return (new_sock, new_sock.getpeername())

        async def connect(self):
            XX

        async def recv(self):
            XX

        async def recv_info(self):
            XX

        async def recvfrom(self):
            XX

        async def recvfrom_into(self):
            XX

        async def send(self):
            XX

        async def sendall(self):
            XX

        async def sendfile(self, file, offset=0, count=None):
            XX

        async def sendmsg(self):
            XX

        async def sendto(self):
            XX

    else:
        # Unix-like
        async def accept(self):
            while True:
                await _core.wait_readable(self)
                try:
                    return self._sock.accept()
                except BlockingIOError:
                    pass

        async def connect(self):
            XX

        async def recv(self):
            XX

        async def recv_info(self):
            XX

        async def recvfrom(self):
            XX

        async def recvfrom_into(self):
            XX

        async def send(self):
            XX

        async def sendall(self):
            XX

        async def sendfile(self, file, offset=0, count=None):
            XX

        async def sendmsg(self):
            XX

        async def sendto(self):
            XX

    # Intentionally omitted:
    #   makefile
    #   setblocking
    #   settimeout
    #   timeout

__all__.append("SocketType")


def create_connection():
    XX
__all__.append("create_connection")
