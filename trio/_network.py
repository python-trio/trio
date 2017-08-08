# "High-level" networking interface

import errno
from contextlib import contextmanager

from . import _core
from . import socket as tsocket
from ._socket import real_socket_type
from ._util import UnLock
from .abc import HalfCloseableStream
from ._streams import ClosedStreamError, BrokenStreamError

__all__ = ["SocketStream", "socket_stream_pair"]

_closed_stream_errnos = {
    # Unix
    errno.EBADF,
    # Windows
    errno.ENOTSOCK,
}


@contextmanager
def _translate_socket_errors_to_stream_errors():
    try:
        yield
    except OSError as exc:
        if exc.errno in _closed_stream_errnos:
            raise ClosedStreamError("this socket was already closed") from None
        else:
            raise BrokenStreamError(
                "socket connection broken: {}".format(exc)
            ) from exc


class SocketStream(HalfCloseableStream):
    """An implementation of the :class:`trio.abc.HalfCloseableStream`
    interface based on a raw network socket.

    Args:
      sock: The trio socket object to wrap. Must have type ``SOCK_STREAM``,
          and be connected.

    By default, :class:`SocketStream` enables ``TCP_NODELAY``, and (on
    platforms where it's supported) enables ``TCP_NOTSENT_LOWAT`` with a
    reasonable buffer size (currently 16 KiB) – see `issue #72
    <https://github.com/python-trio/trio/issues/72>`__ for discussion. You can
    of course override these defaults by calling :meth:`setsockopt`.

    Once a :class:`SocketStream` object is constructed, it implements the full
    :class:`trio.abc.HalfCloseableStream` interface. In addition, it provides
    a few extra features:

    .. attribute:: socket

       The Trio socket object that this stream wraps.

    """

    def __init__(self, sock):
        if not tsocket.is_trio_socket(sock):
            raise TypeError("SocketStream requires trio socket object")
        if real_socket_type(sock.type) != tsocket.SOCK_STREAM:
            raise ValueError("SocketStream requires a SOCK_STREAM socket")
        try:
            sock.getpeername()
        except OSError:
            err = ValueError("SocketStream requires a connected socket")
            raise err from None

        self.socket = sock
        self._send_lock = UnLock(
            _core.ResourceBusyError,
            "another task is currently sending data on this SocketStream"
        )

        # Socket defaults:

        # Not supported on e.g. unix domain sockets
        try:
            self.setsockopt(tsocket.IPPROTO_TCP, tsocket.TCP_NODELAY, True)
        except OSError:
            pass

        if hasattr(tsocket, "TCP_NOTSENT_LOWAT"):
            try:
                # 16 KiB is pretty arbitrary and could probably do with some
                # tuning. (Apple is also setting this by default in CFNetwork
                # apparently -- I'm curious what value they're using, though I
                # couldn't find it online trivially. CFNetwork-129.20 source
                # has no mentions of TCP_NOTSENT_LOWAT. This presentation says
                # "typically 8 kilobytes":
                # http://devstreaming.apple.com/videos/wwdc/2015/719ui2k57m/719/719_your_app_and_next_generation_networks.pdf?dl=1
                # ). The theory is that you want it to be bandwidth *
                # rescheduling interval.
                self.setsockopt(
                    tsocket.IPPROTO_TCP, tsocket.TCP_NOTSENT_LOWAT, 2**14
                )
            except OSError:
                pass

    async def send_all(self, data):
        if self.socket.did_shutdown_SHUT_WR:
            await _core.yield_briefly()
            raise ClosedStreamError("can't send data after sending EOF")
        with self._send_lock.sync:
            with _translate_socket_errors_to_stream_errors():
                await self.socket.sendall(data)

    async def wait_send_all_might_not_block(self):
        async with self._send_lock:
            if self.socket.fileno() == -1:
                raise ClosedStreamError
            with _translate_socket_errors_to_stream_errors():
                await self.socket.wait_writable()

    async def send_eof(self):
        async with self._send_lock:
            # On MacOS, calling shutdown a second time raises ENOTCONN, but
            # send_eof needs to be idempotent.
            if self.socket.did_shutdown_SHUT_WR:
                return
            with _translate_socket_errors_to_stream_errors():
                self.socket.shutdown(tsocket.SHUT_WR)

    async def receive_some(self, max_bytes):
        if max_bytes < 1:
            await _core.yield_briefly()
            raise ValueError("max_bytes must be >= 1")
        with _translate_socket_errors_to_stream_errors():
            return await self.socket.recv(max_bytes)

    async def aclose(self):
        self.socket.close()
        await _core.yield_briefly()

    # __aenter__, __aexit__ inherited from HalfCloseableStream are OK

    def setsockopt(self, level, option, value):
        """Set an option on the underlying socket.

        See :meth:`socket.socket.setsockopt` for details.

        """
        return self.socket.setsockopt(level, option, value)

    def getsockopt(self, level, option, buffersize=0):
        """Check the current value of an option on the underlying socket.

        See :meth:`socket.socket.getsockopt` for details.

        """
        # This is to work around
        #   https://bitbucket.org/pypy/pypy/issues/2561
        # We should be able to drop it when the next PyPy3 beta is released.
        if buffersize == 0:
            return self.socket.getsockopt(level, option)
        else:
            return self.socket.getsockopt(level, option, buffersize)


def socket_stream_pair():
    """Returns a pair of connected :class:`SocketStream` objects.

    This is a convenience function that uses :func:`socket.socketpair` to
    create the sockets, and then converts the result into
    :class:`SocketStream`\s.

    """
    left, right = tsocket.socketpair()
    return SocketStream(left), SocketStream(right)
