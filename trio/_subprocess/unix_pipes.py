import os
from typing import Tuple

from .. import _core, BrokenStreamError
from .._abc import SendStream, ReceiveStream

__all__ = ["PipeSendStream", "PipeReceiveStream", "make_pipe"]


class _PipeMixin:
    def __init__(self, pipefd: int):
        if not isinstance(pipefd, int):
            raise TypeError(
                "{0.__class__.__name__} needs a pipe fd".format(self)
            )

        self._pipe = pipefd
        self._closed = False

    async def aclose(self):
        if self._closed:
            return

        os.close(self._pipe)
        _core.notify_fd_close(self._pipe)
        self._closed = True
        await _core.checkpoint()

    def fileno(self) -> int:
        """Gets the file descriptor for this pipe."""
        return self._pipe

    def __del__(self):
        if self._closed:
            return

        try:
            os.close(self._pipe)
        except AttributeError:
            # probably in interpreter shut down
            pass
        except OSError as e:
            # already closed from somewhere else
            if e.errno != 9:
                raise e from None


class PipeSendStream(_PipeMixin, SendStream):
    """Represents a send stream over an os.pipe object."""

    async def send_all(self, data: bytes):
        if self._closed:
            await _core.checkpoint()
            raise _core.ClosedResourceError("this pipe is already closed")

        if not data:
            await _core.checkpoint()
            return

        length = len(data)
        # adapted from the SocketStream code
        with memoryview(data) as view:
            total_sent = 0
            while total_sent < length:
                with view[total_sent:] as remaining:
                    try:
                        total_sent += os.write(self._pipe, remaining)
                    except BrokenPipeError as e:
                        await _core.checkpoint()
                        raise BrokenStreamError from e
                    except BlockingIOError:
                        pass

                await self.wait_send_all_might_not_block()

    async def wait_send_all_might_not_block(self) -> None:
        if self._closed:
            await _core.checkpoint()
            raise _core.ClosedResourceError("This pipe is already closed")

        await _core.wait_writable(self._pipe)


class PipeReceiveStream(_PipeMixin, ReceiveStream):
    """Represents a receive stream over an os.pipe object."""

    async def receive_some(self, max_bytes: int) -> bytes:
        if self._closed:
            await _core.checkpoint()
            raise _core.ClosedResourceError("this pipe is already closed")

        if not isinstance(max_bytes, int):
            await _core.checkpoint()
            raise TypeError("max_bytes must be integer >= 1")

        if max_bytes < 1:
            await _core.checkpoint()
            raise ValueError("max_bytes must be integer >= 1")

        while True:
            try:
                data = os.read(self._pipe, max_bytes)
            except BlockingIOError:
                await _core.wait_readable(self._pipe)
            else:
                break

        return data


async def make_pipe() -> Tuple[PipeSendStream, PipeReceiveStream]:
    """Makes a new pair of pipes."""
    (r, w) = os.pipe2(os.O_NONBLOCK)
    return PipeSendStream(w), PipeReceiveStream(r)
