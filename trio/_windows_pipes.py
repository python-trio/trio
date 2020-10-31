import sys
from typing import TYPE_CHECKING
from . import _core
from ._abc import SendStream, ReceiveStream, SendChannel, ReceiveChannel
from ._util import ConflictDetector, Final
from ._core._windows_cffi import (
    _handle,
    raise_winerror,
    kernel32,
    ffi,
    ErrorCodes,
)

assert sys.platform == "win32" or not TYPE_CHECKING

# XX TODO: don't just make this up based on nothing.
DEFAULT_RECEIVE_SIZE = 65536


# See the comments on _unix_pipes._FdHolder for discussion of why we set the
# handle to -1 when it's closed.
class _HandleHolder:
    def __init__(self, handle: int) -> None:
        self.handle = -1
        if not isinstance(handle, int):
            raise TypeError("handle must be an int")
        self.handle = handle
        _core.register_with_iocp(self.handle)

    @property
    def closed(self):
        return self.handle == -1

    def _close(self):
        if self.closed:
            return
        handle = self.handle
        self.handle = -1
        if not kernel32.CloseHandle(_handle(handle)):
            raise_winerror()

    async def aclose(self):
        self._close()
        await _core.checkpoint()

    def __del__(self):
        self._close()


class PipeSendStream(SendStream, metaclass=Final):
    """Represents a send stream over a Windows named pipe that has been
    opened in OVERLAPPED mode.
    """

    def __init__(self, handle: int) -> None:
        self._handle_holder = _HandleHolder(handle)
        self._conflict_detector = ConflictDetector(
            "another task is currently using this pipe"
        )

    async def send_all(self, data: bytes):
        with self._conflict_detector:
            if self._handle_holder.closed:
                raise _core.ClosedResourceError("this pipe is already closed")

            if not data:
                await _core.checkpoint()
                return

            try:
                written = await _core.write_overlapped(self._handle_holder.handle, data)
            except BrokenPipeError as ex:
                raise _core.BrokenResourceError from ex
            # By my reading of MSDN, this assert is guaranteed to pass so long
            # as the pipe isn't in nonblocking mode, but... let's just
            # double-check.
            assert written == len(data)

    async def wait_send_all_might_not_block(self) -> None:
        with self._conflict_detector:
            if self._handle_holder.closed:
                raise _core.ClosedResourceError("This pipe is already closed")

            # not implemented yet, and probably not needed
            await _core.checkpoint()

    async def aclose(self):
        await self._handle_holder.aclose()


class PipeReceiveStream(ReceiveStream, metaclass=Final):
    """Represents a receive stream over an os.pipe object."""

    def __init__(self, handle: int) -> None:
        self._handle_holder = _HandleHolder(handle)
        self._conflict_detector = ConflictDetector(
            "another task is currently using this pipe"
        )

    async def receive_some(self, max_bytes=None) -> bytes:
        with self._conflict_detector:
            if self._handle_holder.closed:
                raise _core.ClosedResourceError("this pipe is already closed")

            if max_bytes is None:
                max_bytes = DEFAULT_RECEIVE_SIZE
            else:
                if not isinstance(max_bytes, int):
                    raise TypeError("max_bytes must be integer >= 1")
                if max_bytes < 1:
                    raise ValueError("max_bytes must be integer >= 1")

            buffer = bytearray(max_bytes)
            try:
                size = await _core.readinto_overlapped(
                    self._handle_holder.handle, buffer
                )
            except BrokenPipeError:
                if self._handle_holder.closed:
                    raise _core.ClosedResourceError(
                        "another task closed this pipe"
                    ) from None

                # Windows raises BrokenPipeError on one end of a pipe
                # whenever the other end closes, regardless of direction.
                # Convert this to the Unix behavior of returning EOF to the
                # reader when the writer closes.
                #
                # And since we're not raising an exception, we have to
                # checkpoint. But readinto_overlapped did raise an exception,
                # so it might not have checkpointed for us. So we have to
                # checkpoint manually.
                await _core.checkpoint()
                return b""
            else:
                del buffer[size:]
                return buffer

    async def aclose(self):
        await self._handle_holder.aclose()


class PipeSendChannel(SendChannel[bytes]):
    """Represents a message stream over a pipe object."""

    def __init__(self, handle: int) -> None:
        self._pss = PipeSendStream(handle)
        # needed for "detach" via _handle_holder.handle = -1
        self._handle_holder = self._pss._handle_holder

    async def send(self, value: bytes):
        # Works just fine if the pipe is message-oriented
        await self._pss.send_all(value)

    async def aclose(self):
        await self._handle_holder.aclose()


class PipeReceiveChannel(ReceiveChannel[bytes]):
    """Represents a message stream over a pipe object."""

    def __init__(self, handle: int) -> None:
        self._handle_holder = _HandleHolder(handle)
        self._conflict_detector = ConflictDetector(
            "another task is currently using this pipe"
        )

    async def receive(self) -> bytes:
        # Would a io.BytesIO make more sense?
        buffer = bytearray(DEFAULT_RECEIVE_SIZE)
        try:
            return await self._receive_some_into(buffer)
        except OSError as e:
            if e.winerror != ErrorCodes.ERROR_MORE_DATA:
                raise  # pragma: no cover
            left = ffi.new("LPDWORD")
            if not kernel32.PeekNamedPipe(
                _handle(self._handle_holder.handle),
                ffi.NULL,
                0,
                ffi.NULL,
                ffi.NULL,
                left,
            ):
                raise_winerror()  # pragma: no cover
            buffer.extend(await self._receive_some_into(bytearray(left[0])))
            return buffer

    async def _receive_some_into(self, buffer) -> bytes:
        with self._conflict_detector:
            if self._handle_holder.closed:
                raise _core.ClosedResourceError("this pipe is already closed")
            try:
                size = await _core.readinto_overlapped(
                    self._handle_holder.handle, buffer
                )
            except BrokenPipeError:
                if self._handle_holder.closed:
                    raise _core.ClosedResourceError(
                        "another task closed this pipe"
                    ) from None

                # Windows raises BrokenPipeError on one end of a pipe
                # whenever the other end closes, regardless of direction.
                # Convert this to EndOfChannel
                #
                # And since we're not raising an exception, we have to
                # checkpoint. But readinto_overlapped did raise an exception,
                # so it might not have checkpointed for us. So we have to
                # checkpoint manually.
                await _core.checkpoint()
                raise _core.EndOfChannel
            else:
                del buffer[size:]
                return buffer

    async def aclose(self):
        await self._handle_holder.aclose()
