import fcntl
import os
import errno
from typing import Optional, List

from ._abc import SendStream, ReceiveStream
from ._util import ConflictDetector

import trio


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
        # make sure self.fd is always initialized to *something*, because even
        # if we error out here then __del__ will run and access it.
        self.fd = -1
        if not isinstance(fd, int):
            raise TypeError("file descriptor must be an int")
        self.fd = fd
        # Store original state, and ensure non-blocking mode is enabled
        self._original_flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        fcntl.fcntl(
            self.fd, fcntl.F_SETFL, self._original_flags | os.O_NONBLOCK
        )

    @property
    def closed(self):
        return self.fd == -1

    def _raw_close(self):
        # This doesn't assume it's in a Trio context, so it can be called from
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
        fcntl.fcntl(fd, fcntl.F_SETFL, self._original_flags)
        os.close(fd)

    def __del__(self):
        self._raw_close()

    async def aclose(self):
        if not self.closed:
            trio.hazmat.notify_closing(self.fd)
            self._raw_close()
        await trio.hazmat.checkpoint()


# TODO: remove
class PipeSendStream(SendStream):
    """Represents a send stream over an os.pipe object."""

    def __init__(self, fd: int):
        self._fd_holder = _FdHolder(fd)
        self._conflict_detector = ConflictDetector(
            "another task is using this pipe"
        )

    async def send_all(self, data: bytes):
        with self._conflict_detector:
            # have to check up front, because send_all(b"") on a closed pipe
            # should raise
            if self._fd_holder.closed:
                raise trio.ClosedResourceError("this pipe was already closed")
            await trio.hazmat.checkpoint()
            length = len(data)
            # adapted from the SocketStream code
            with memoryview(data) as view:
                sent = 0
                while sent < length:
                    with view[sent:] as remaining:
                        try:
                            sent += os.write(self._fd_holder.fd, remaining)
                        except BlockingIOError:
                            await trio.hazmat.wait_writable(self._fd_holder.fd)
                        except OSError as e:
                            if e.errno == errno.EBADF:
                                raise trio.ClosedResourceError(
                                    "this pipe was closed"
                                ) from None
                            else:
                                raise trio.BrokenResourceError from e

    async def wait_send_all_might_not_block(self) -> None:
        with self._conflict_detector:
            if self._fd_holder.closed:
                raise trio.ClosedResourceError("this pipe was already closed")
            try:
                await trio.hazmat.wait_writable(self._fd_holder.fd)
            except BrokenPipeError as e:
                # kqueue: raises EPIPE on wait_writable instead
                # of sending, which is annoying
                raise trio.BrokenResourceError from e

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
        with self._conflict_detector:
            if not isinstance(max_bytes, int):
                raise TypeError("max_bytes must be integer >= 1")

            if max_bytes < 1:
                raise ValueError("max_bytes must be integer >= 1")

            await trio.hazmat.checkpoint()
            while True:
                try:
                    data = os.read(self._fd_holder.fd, max_bytes)
                except BlockingIOError:
                    await trio.hazmat.wait_readable(self._fd_holder.fd)
                except OSError as e:
                    if e.errno == errno.EBADF:
                        raise trio.ClosedResourceError(
                            "this pipe was closed"
                        ) from None
                    else:
                        raise trio.BrokenResourceError from e
                else:
                    break

            return data

    async def aclose(self):
        await self._fd_holder.aclose()

    def fileno(self):
        return self._fd_holder.fd


class FdStream(SendStream, ReceiveStream):
    """
    Represents a send and/or receive stream given file descriptor(s) to
    a pipe, TTY, etc.

    *send_fd*/*receive_fd* must refer to a file that is open for
    reading/writing and supports non-blocking I/O (pipes and TTYs will work,
    on-disk files probably not).  The returned stream takes ownership of the
    fd(s), so closing the stream will close the fd(s) too.  As with
    `os.fdopen`, you should not directly use an fd after you have wrapped it in
    a stream using thisfunction.

    Where an fd supports both read and write, pass the same fd to *send_fd* and
    *receive_fd*.

    Args:
      send_fd (int on None): The send stream fd.
      receive_fd (int or None): The receive stream fd.

    Returns:
      A new `FdStream` object.

    Raises:
      ValueError: if both *send_fd* and *receive_fd* are None.
    """

    def __init__(
        self, send_fd: Optional[int] = None, receive_fd: Optional[int] = None
    ):
        if (send_fd, receive_fd) == (None, None):
            raise ValueError('Expected send_fd or receive_fd')
        self._send_conflict_detector = ConflictDetector(
            "another task is using this stream for send"
        )
        self._receive_conflict_detector = ConflictDetector(
            "another task is using this stream for receive"
        )
        # NOTE: if send is supported, it's always represented by first
        # fd holder in the list.
        self._fd_holders = []  # type: List[_FdHolder]
        if send_fd == receive_fd:
            self._fd_holders.append(_FdHolder(send_fd))
        else:
            if send_fd is not None:
                self._fd_holders.append(_FdHolder(send_fd))
            if receive_fd is not None:
                self._fd_holders.append(_FdHolder(receive_fd))
        self._send_fd = send_fd
        self._receive_fd = receive_fd

    async def send_all(self, data: bytes):
        if self._send_fd is None:
            raise RuntimeError('stream does not support send')
        with self._send_conflict_detector:
            # have to check up front, because send_all(b"") on a closed pipe
            # should raise
            if self._fd_holders[0].closed:
                raise trio.ClosedResourceError("send file was already closed")
            await trio.hazmat.checkpoint()
            length = len(data)
            # adapted from the SocketStream code
            with memoryview(data) as view:
                sent = 0
                while sent < length:
                    with view[sent:] as remaining:
                        try:
                            sent += os.write(self._send_fd, remaining)
                        except BlockingIOError:
                            await trio.hazmat.wait_writable(self._send_fd)
                        except OSError as e:
                            if e.errno == errno.EBADF:
                                raise trio.ClosedResourceError(
                                    "send file was closed"
                                ) from None
                            else:
                                raise trio.BrokenResourceError from e

    async def wait_send_all_might_not_block(self) -> None:
        if self._send_fd is None:
            raise RuntimeError('stream does not support send')
        with self._send_conflict_detector:
            if self._fd_holders[0].closed:
                raise trio.ClosedResourceError("send file was already closed")
            try:
                await trio.hazmat.wait_writable(self._send_fd)
            except BrokenPipeError as e:
                # kqueue: raises EPIPE on wait_writable instead
                # of sending, which is annoying
                raise trio.BrokenResourceError from e

    async def receive_some(self, max_bytes: int) -> bytes:
        with self._receive_conflict_detector:
            if not isinstance(max_bytes, int):
                raise TypeError("max_bytes must be integer >= 1")

            if max_bytes < 1:
                raise ValueError("max_bytes must be integer >= 1")

            await trio.hazmat.checkpoint()
            while True:
                try:
                    data = os.read(self._receive_fd, max_bytes)
                except BlockingIOError:
                    await trio.hazmat.wait_readable(self._receive_fd)
                except OSError as e:
                    if e.errno == errno.EBADF:
                        raise trio.ClosedResourceError(
                            "receive file was closed"
                        ) from None
                    else:
                        raise trio.BrokenResourceError from e
                else:
                    break

            return data

    async def aclose(self):
        for fd_holder in self._fd_holders:
            await fd_holder.aclose()

    def send_fileno(self):
        if self._send_fd is None:
            raise RuntimeError('stream does not support send')
        return self._send_fd

    def receive_fileno(self):
        if self._receive_fd is None:
            raise RuntimeError('stream does not support receive')
        return self._receive_fd
