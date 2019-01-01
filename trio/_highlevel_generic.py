import attr

from . import _core
from .abc import HalfCloseableStream


async def aclose_forcefully(resource):
    """Close an async resource or async generator immediately, without
    blocking to do any graceful cleanup.

    :class:`~trio.abc.AsyncResource` objects guarantee that if their
    :meth:`~trio.abc.AsyncResource.aclose` method is cancelled, then they will
    still close the resource (albeit in a potentially ungraceful
    fashion). :func:`aclose_forcefully` is a convenience function that
    exploits this behavior to let you force a resource to be closed without
    blocking: it works by calling ``await resource.aclose()`` and then
    cancelling it immediately.

    Most users won't need this, but it may be useful on cleanup paths where
    you can't afford to block, or if you want to close a resource and don't
    care about handling it gracefully. For example, if
    :class:`~trio.ssl.SSLStream` encounters an error and cannot perform its
    own graceful close, then there's no point in waiting to gracefully shut
    down the underlying transport either, so it calls ``await
    aclose_forcefully(self.transport_stream)``.

    Note that this function is async, and that it acts as a checkpoint, but
    unlike most async functions it cannot block indefinitely (at least,
    assuming the underlying resource object is correctly implemented).

    """
    with _core.open_cancel_scope() as cs:
        cs.cancel()
        await resource.aclose()


@attr.s(cmp=False, hash=False)
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

          left, right = trio.testing.memory_stream_pair()
          echo_stream = StapledStream(SocketStream(left), SocketStream(right))
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
        calls ``self.send_stream.aclose()``.

        """
        if hasattr(self.send_stream, "send_eof"):
            return await self.send_stream.send_eof()
        else:
            return await self.send_stream.aclose()

    async def receive_some(self, max_bytes):
        """Calls ``self.receive_stream.receive_some``.

        """
        return await self.receive_stream.receive_some(max_bytes)

    async def aclose(self):
        """Calls ``aclose`` on both underlying streams.

        """
        try:
            await self.send_stream.aclose()
        finally:
            await self.receive_stream.aclose()


class NullStream(HalfCloseableStream):
    """A :class:`~trio.abc.HalfCloseableStream` in which any data sent is
    immediately discarded and receives always return end-of-file.

    This is useful for similar reasons as ``/dev/null`` on Unix; for example,
    in a function defined to return a stream of data, it reduces special-casing
    if there's no data that needs to be provided.

    Trying to read after closing, or write after closing or
    :meth:`~trio.abc.HalfCloseableStream.send_eof`, will raise
    :exc:`ClosedResourceError`, even though those operations are
    otherwise no-ops.

    A synchronous ``close()`` is provided in addition to the usual ``aclose()``.
    """

    def __init__(self) -> None:
        self._read_closed = False
        self._write_closed = False

    def __repr__(self) -> str:
        if self._read_closed:
            closed = "closed"
        elif self._write_closed:
            closed = "sent EOF"
        else:
            closed = "open"
        return "<trio.NullStream: {}>".format(closed)

    def close(self) -> None:
        self._read_closed = self._write_closed = True

    async def aclose(self) -> None:
        self.close()
        await _core.checkpoint()

    async def receive_some(self, max_bytes: int) -> bytes:
        await _core.checkpoint()
        if self._read_closed:
            raise _core.ClosedResourceError
        return b""

    async def send_all(self, data: bytes) -> None:
        await _core.checkpoint()
        if self._write_closed:
            raise _core.ClosedResourceError

    async def wait_send_all_might_not_block(self) -> None:
        await _core.checkpoint()
        if self._write_closed:
            raise _core.ClosedResourceError

    async def send_eof(self) -> None:
        await _core.checkpoint()
        if self._read_closed:
            raise _core.ClosedResourceError
        self._write_closed = True
