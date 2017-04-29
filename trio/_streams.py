import abc
import contextlib

import attr

from . import _core
from .abc import StreamWithSendEOF

__all__ = [
    "StapledStream",
]

@attr.s(slots=True, cmp=False, hash=False)
class StapledStream(StreamWithSendEOF):
    """This class `staples <https://en.wikipedia.org/wiki/Staple_(fastener)>`__
    together two unidirectional streams to make single bidirectional stream.

    Args:
      send_stream (~trio.abc.SendStream): The stream to use for sending.
      recv_stream (~trio.abc.RecvStream): The stream to use for receiving.

    Example:

       A silly and deadlock-prone way to make a stream that echoes back
       whatever you write to it::

          sock1, sock2 = trio.socket.socketpair()
          echo_stream = StapledStream(sock1, sock2)
          await echo_stream.sendall(b"x")
          assert await echo_stream.recv(1) == b"x"

    :class:`StapledStream` objects have two public attributes:

    .. attribute:: send_stream

       The underlying :class:`~trio.abc.SendStream`. :meth:`sendall` and
       :meth:`wait_sendall_might_not_block` are delegated to this object.

    .. attribute:: recv_stream

       The underlying :class:`~trio.abc.RecvStream`. :meth:`recv` is delegated
       to this object.

    They also, of course, implement the methods in the
    :class:`~trio.abc.StreamWithSendEOF` interface:

    """
    send_stream = attr.ib()
    recv_stream = attr.ib()

    async def sendall(self, data):
        """Calls ``self.send_stream.sendall``.

        """
        return await self.send_stream.sendall(data)

    async def wait_sendall_might_not_block(self):
        """Calls ``self.send_stream.wait_sendall_might_not_block``.

        """
        return await self.send_stream.wait_sendall_might_not_block()

    async def send_eof(self):
        """Shuts down the send side of the stream.

        If ``self.send_stream.send_eof`` exists, then calls it. Otherwise,
        calls ``self.send_stream.graceful_close()``.

        """
        if hasattr(self.send_stream, "send_eof"):
            return await self.send_stream.send_eof()
        else:
            return await self.send_stream.graceful_close()

    async def recv(self, max_bytes):
        """Calls ``self.recv_stream.recv``.

        """
        return await self.recv_stream.recv(max_bytes)

    def forceful_close(self):
        """Calls ``forceful_close`` on both underlying streams.

        """
        try:
            self.send_stream.forceful_close()
        finally:
            self.recv_stream.forceful_close()

    async def graceful_close(self):
        """Calls ``graceful_close`` on both underlying streams.

        """
        try:
            await self.send_stream.graceful_close()
        finally:
            await self.recv_stream.graceful_close()
