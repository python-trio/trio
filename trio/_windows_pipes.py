import os
from typing import Tuple

from . import _core
from ._abc import SendStream, ReceiveStream
from ._util import ConflictDetector
from ._core._windows_cffi import _handle, raise_winerror, kernel32, ffi

__all__ = ["PipeSendStream", "PipeReceiveStream", "make_pipe"]


class _PipeMixin:
    def __init__(self, pipe_handle: int) -> None:
        self._pipe = _handle(pipe_handle)
        _core.register_with_iocp(self._pipe)
        self._closed = False
        self._conflict_detector = ConflictDetector(
            "another task is currently {}ing data on this pipe".format(
                type(self).__name__[4:-5].lower()  # "send" or "receive"
            )
        )

    def _close(self):
        if self._closed:
            return

        self._closed = True
        if not kernel32.CloseHandle(self._pipe):
            raise_winerror()

    async def aclose(self):
        self._close()
        await _core.checkpoint()

    def __del__(self):
        self._close()


class PipeSendStream(_PipeMixin, SendStream):
    """Represents a send stream over a Windows named pipe that has been
    opened in OVERLAPPED mode.
    """

    async def send_all(self, data: bytes):
        # adapted from the SocketStream code
        async with self._conflict_detector:
            if self._closed:
                raise _core.ClosedResourceError("this pipe is already closed")

            if not data:
                return

            # adapted from the SocketStream code
            length = len(data)
            with memoryview(data) as view:
                total_sent = 0
                while total_sent < length:
                    # Only send 64K at a time. IOCP buffers can sometimes
                    # get pinned in kernel memory and we don't want to use
                    # an arbitrary amount.
                    with view[total_sent:total_sent + 65536] as chunk:
                        try:
                            total_sent += await _core.write_overlapped(
                                self._pipe, chunk
                            )
                        except BrokenPipeError as ex:
                            raise _core.BrokenResourceError from ex

    async def wait_send_all_might_not_block(self) -> None:
        async with self._conflict_detector:
            if self._closed:
                raise _core.ClosedResourceError("This pipe is already closed")

            # not implemented yet, and probably not needed
            pass


class PipeReceiveStream(_PipeMixin, ReceiveStream):
    """Represents a receive stream over an os.pipe object."""

    async def receive_some(self, max_bytes: int) -> bytes:
        async with self._conflict_detector:
            if self._closed:
                raise _core.ClosedResourceError("this pipe is already closed")

            if not isinstance(max_bytes, int):
                raise TypeError("max_bytes must be integer >= 1")

            if max_bytes < 1:
                raise ValueError("max_bytes must be integer >= 1")

            buffer = bytearray(max_bytes)
            try:
                size = await _core.readinto_overlapped(self._pipe, buffer)
            except BrokenPipeError:
                if self._closed:
                    raise _core.ClosedResourceError(
                        "another task closed this pipe"
                    ) from None

                # Windows raises BrokenPipeError on one end of a pipe
                # whenever the other end closes, regardless of direction.
                # Convert this to the Unix behavior of returning EOF to the
                # reader when the writer closes.
                return b""
            else:
                del buffer[size:]
                return buffer


async def make_pipe() -> Tuple[PipeSendStream, PipeReceiveStream]:
    """Makes a new pair of pipes."""
    from asyncio.windows_utils import pipe
    (r, w) = pipe()
    return PipeSendStream(w), PipeReceiveStream(r)
