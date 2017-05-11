# "High-level" networking interface

import errno
from contextlib import contextmanager

from . import socket as tsocket
from .abc import HalfCloseableStream
from ._streams import ClosedStreamError, BrokenStreamError

__all__ = ["SocketStream", "socket_stream_pair"]

_closed_stream_errnos = {
    # Unix
    errno.EBADF,
    # Windows
    errno.ENOTSOCK,
}
# XXXXX EPIPE on send_all *can* just mean send_eof was called :-(
# that's what I get on Linux and MacOS
# on Windows it's WSAESHUTDOWN, which is fair, though probably we only want
# this on send_all not receive_some

@contextmanager
def _translate_socket_errors_to_stream_errors():
    try:
        yield
    except OSError as exc:
        if exc.errno in _closed_stream_errnos:
            raise ClosedStreamError(
                "this socket was already closed") from None
        else:
            raise BrokenStreamError(
                "socket connection broken: {}".format(exc)) from exc

class SocketStream(HalfCloseableStream):
    def __init__(self, sock):
        if not isinstance(sock, tsocket.SocketType):
            raise TypeError("SocketStream requires trio.socket.SocketType")
        if sock._real_type != tsocket.SOCK_STREAM:
            raise TypeError("SocketStream requires a SOCK_STREAM socket")
        try:
            sock.getpeername()
        except OSError:
            err = TypeError("SocketStream requires a connected socket")
            raise err from None
        self.socket = sock

    async def send_all(self, data):
        if self.socket._did_SHUT_WR:
            await _core.yield_briefly()
            raise ClosedStreamError("can't send data after sending EOF")
        with _translate_socket_errors_to_stream_errors():
            await self.socket.sendall(data)

    async def wait_send_all_might_not_block(self):
        with _translate_socket_errors_to_stream_errors():
            await self.socket.wait_writable()

    async def send_eof(self):
        await _core.yield_briefly()
        with _translate_socket_errors_to_stream_errors():
            self.socket.shutdown(SHUT_WR)

    async def receive_some(self, max_bytes):
        with _translate_socket_errors_to_stream_errors():
            return await self.socket.recv(max_bytes)

    def forceful_close(self):
        self.socket.close()

    # graceful_close, __aenter__, __aexit__ inherited from HalfCloseableStream
    # are OK

    def getsockopt(self, level, option, buffersize=0):
        return self.socket.getsockopt(level, option, buffersize)

    def setsockopt(self, level, option, value):
        return self.socket.setsockopt(level, option, value)


def socket_stream_pair():
    left, right = tsocket.socketpair()
    return SocketStream(left), SocketStream(right)
