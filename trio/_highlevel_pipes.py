import os
from typing import Tuple

from . import _core
from ._abc import SendStream, ReceiveStream
from ._highlevel_socket import _translate_socket_errors_to_stream_errors

__all__ = ["PipeSendStream", "PipeReceiveStream", "make_pipe"]


class _PipeMixin:
    def __init__(self, pipefd: int):
        if not isinstance(pipefd, int):
            raise TypeError("PipeSendStream needs a pipe fd")

        self._pipe = pipefd

    async def aclose(self):
        os.close(self._pipe)

    def fileno(self) -> int:
        """Gets the file descriptor for this pipe."""
        return self._pipe


class PipeSendStream(_PipeMixin, SendStream):
    """Represents a send stream over an os.pipe object."""

    async def send_all(self, data: bytes):
        length = len(data)
        # adapted from the SocketStream code
        with memoryview(data) as view, \
                _translate_socket_errors_to_stream_errors():
            total_sent = 0
            while total_sent < length:
                with view[total_sent:] as remaining:
                    total_sent += os.write(self._pipe, remaining)

                await self.wait_send_all_might_not_block()

    async def wait_send_all_might_not_block(self) -> None:
        await _core.wait_socket_writable(self._pipe)


class PipeReceiveStream(_PipeMixin, ReceiveStream):
    """Represents a receive stream over an os.pipe object."""

    async def receive_some(self, max_bytes: int) -> bytes:
        if max_bytes < 1:
            await _core.checkpoint()
            raise ValueError("max_bytes must be >= 1")

        with _translate_socket_errors_to_stream_errors():
            await _core.wait_socket_readable(self._pipe)
            data = os.read(self._pipe, max_bytes)

        return data


def make_pipe() -> Tuple[PipeReceiveStream, PipeSendStream]:
    """Makes a new pair of pipes."""
    (r, w) = os.pipe2(os.O_NONBLOCK)
    return PipeReceiveStream(r), PipeSendStream(w)
