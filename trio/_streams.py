import abc
import contextlib

import attr

from . import _core
from .abc import HalfCloseableStream

__all__ = [
    "BrokenStreamError", "ClosedStreamError", "StapledStream",
]

class BrokenStreamError(Exception):
    """Raised when an attempt to use a stream a stream fails due to external
    circumstances.

    For example, you might get this if you try to send data on a stream where
    the remote side has already closed the connection.

    You *don't* get this error if *you* closed the stream – in that case you
    get :class:`ClosedStreamError`.

    This exception's ``__cause__`` attribute will often contain more
    information about the underlying error.

    """
    pass


class ClosedStreamError(Exception):
    """Raised when an attempt to use a stream a stream fails because the
    stream was already closed locally.

    You *only* get this error if *your* code closed the stream object you're
    attempting to use by calling
    :meth:`~trio.abc.AsyncResource.graceful_close` or
    similar. (:meth:`~trio.abc.SendStream.send_all` might also raise this if
    you already called :meth:`~trio.abc.HalfCloseableStream.send_eof`.)
    Therefore this exception generally indicates a bug in your code.

    If a problem arises elsewhere, for example due to a network failure or a
    misbehaving peer, then you get :class:`BrokenStreamError` instead.

    """
    pass


@attr.s(slots=True, cmp=False, hash=False)
class StapledStream(HalfCloseableStream):
    """This class `staples <https://en.wikipedia.org/wiki/Staple_(fastener)>`__
    together two unidirectional streams to make single bidirectional stream.

    Args:
      send_stream (~trio.abc.SendStream): The stream to use for sending.
      receive_stream (~trio.abc.ReceiveStream): The stream to use for
          receiving.

    Example:

       A silly way to make a stream that echoes back whatever you write to
       it::

          sock1, sock2 = trio.socket.socketpair()
          echo_stream = StapledStream(SocketStream(sock1), SocketStream(sock2))
          await echo_stream.send_all(b"x")
          assert await echo_stream.receive_some(1) == b"x"

    :class:`StapledStream` objects implement the methods in the
    :class:`~trio.abc.HalfCloseableStream` interface. They also have two
    additional public attributes:

    .. attribute:: send_stream

       The underlying :class:`~trio.abc.SendStream`. :meth:`send_all` and
       :meth:`wait_send_all_might_not_block` are delegated to this object.

    .. attribute:: receive_stream

       The underlying :class:`~trio.abc.ReceiveStream`. :meth:`receive_some`
       is delegated to this object.

    """
    send_stream = attr.ib()
    receive_stream = attr.ib()

    async def send_all(self, data):
        """Calls ``self.send_stream.send_all``.

        """
        return await self.send_stream.send_all(data)

    async def wait_send_all_might_not_block(self):
        """Calls ``self.send_stream.wait_send_all_might_not_block``.

        """
        return await self.send_stream.wait_send_all_might_not_block()

    async def send_eof(self):
        """Shuts down the send side of the stream.

        If ``self.send_stream.send_eof`` exists, then calls it. Otherwise,
        calls ``self.send_stream.graceful_close()``.

        """
        if hasattr(self.send_stream, "send_eof"):
            return await self.send_stream.send_eof()
        else:
            return await self.send_stream.graceful_close()

    async def receive_some(self, max_bytes):
        """Calls ``self.receive_stream.receive_some``.

        """
        return await self.receive_stream.receive_some(max_bytes)

    def forceful_close(self):
        """Calls ``forceful_close`` on both underlying streams.

        """
        try:
            self.send_stream.forceful_close()
        finally:
            self.receive_stream.forceful_close()

    async def graceful_close(self):
        """Calls ``graceful_close`` on both underlying streams.

        """
        try:
            await self.send_stream.graceful_close()
        finally:
            await self.receive_stream.graceful_close()
