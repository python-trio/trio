import fcntl
import os
from typing import Tuple
import errno

from . import _core
from ._abc import SendStream, ReceiveStream
from ._util import ConflictDetector

__all__ = ["PipeSendStream", "PipeReceiveStream", "make_pipe"]


class _FdHolder:
    # This class holds onto a raw file descriptor, in non-blocking mode, and
    # is responsible for managing its lifecycle. In particular, it's
    # responsible for making sure it gets closed, and also for tracking
    # whether it's been closed.
    #
    # The way we track closure is to set the .fd field to -1, discarding the
    # original value. You might think that this is a strange idea, since it
    # overloads the same field to do two different things. Wouldn't it be more
    # natural to have a dedicated .closed field? But that would be more
    # error-prone. Fds are represented by small integers, and once an fd is
    # closed, its integer value may be reused immediately. If we accidentally
    # used the old fd after being closed, we might end up doing something to
    # another unrelated fd that happened to get assigned the same integer
    # value. By throwing away the integer value immediately, it becomes
    # impossible to make this mistake – we'll just get an EBADF.
    #
    # (This trick was copied from the stdlib socket module.)
    def __init__(self, fd: int):
        if not isinstance(fd, int):
            raise TypeError("file descriptor must be an int")
        self.fd = fd
        # Flip the fd to non-blocking mode
        flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        fcntl.fcntl(self.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    @property
    def closed(self):
        return self.fd == -1

    def _raw_close(self):
        # This doesn't assume it's in a trio context, so it can be called from
        # __del__. You should never call it from Trio context, because it
        # skips calling notify_fd_close. But from __del__, skipping that is
        # OK, because notify_fd_close just wakes up other tasks that are
        # waiting on this fd, and those tasks hold a reference to this object.
        # So if __del__ is being called, we know there aren't any tasks that
        # need to be woken.
        if self.closed:
            return
        fd = self.fd
        self.fd = -1
        os.close(fd)

    def __del__(self):
        self._raw_close()

    async def aclose(self):
        if not self.closed:
            _core.notify_fd_close(self.fd)
            self._raw_close()
        await _core.checkpoint()


class PipeSendStream(SendStream):
    """Represents a send stream over an os.pipe object."""

    def __init__(self, fd: int):
        self._fd_holder = _FdHolder(fd)
        self._conflict_detector = ConflictDetector(
            "another task is using this pipe"
        )

    async def send_all(self, data: bytes):
        async with self._conflict_detector:
            # have to check up front, because send_all(b"") on a closed pipe
            # should raise
            if self._fd_holder.closed:
                raise _core.ClosedResourceError("this pipe was already closed")

            length = len(data)
            # adapted from the SocketStream code
            with memoryview(data) as view:
                sent = 0
                while sent < length:
                    with view[sent:] as remaining:
                        try:
                            sent += os.write(self._fd_holder.fd, remaining)
                        except BlockingIOError:
                            await _core.wait_writable(self._fd_holder.fd)
                        except OSError as e:
                            if e.errno == errno.EBADF:
                                raise _core.ClosedResourceError(
                                    "this pipe was closed"
                                ) from None
                            else:
                                raise _core.BrokenResourceError from e

    async def wait_send_all_might_not_block(self) -> None:
        async with self._conflict_detector:
            if self._fd_holder.closed:
                raise _core.ClosedResourceError("this pipe was already closed")
            try:
                await _core.wait_writable(self._fd_holder.fd)
            except BrokenPipeError as e:
                # kqueue: raises EPIPE on wait_writable instead
                # of sending, which is annoying
                raise _core.BrokenResourceError from e

    async def aclose(self):
        await self._fd_holder.aclose()

    def fileno(self):
        return self._fd_holder.fd


class PipeReceiveStream(ReceiveStream):
    """Represents a receive stream over an os.pipe object."""

    def __init__(self, fd: int):
        self._fd_holder = _FdHolder(fd)
        self._conflict_detector = ConflictDetector(
            "another task is using this pipe"
        )

    async def receive_some(self, max_bytes: int) -> bytes:
        async with self._conflict_detector:
            if not isinstance(max_bytes, int):
                raise TypeError("max_bytes must be integer >= 1")

            if max_bytes < 1:
                raise ValueError("max_bytes must be integer >= 1")

            while True:
                try:
                    data = os.read(self._fd_holder.fd, max_bytes)
                except BlockingIOError:
                    await _core.wait_readable(self._fd_holder.fd)
                except OSError as e:
                    await _core.cancel_shielded_checkpoint()
                    if e.errno == errno.EBADF:
                        raise _core.ClosedResourceError(
                            "this pipe was closed"
                        ) from None
                    else:
                        raise _core.BrokenResourceError from e
                else:
                    break

            return data

    async def aclose(self):
        await self._fd_holder.aclose()

    def fileno(self):
        return self._fd_holder.fd


async def make_pipe() -> Tuple[PipeSendStream, PipeReceiveStream]:
    """Makes a new pair of pipes."""
    (r, w) = os.pipe()
    return PipeSendStream(w), PipeReceiveStream(r)
