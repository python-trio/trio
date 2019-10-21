import os
import errno

from ._abc import Stream
from ._util import ConflictDetector

import trio

if os.name != "posix":
    # We raise an error here rather than gating the import in hazmat.py
    # in order to keep jedi static analysis happy.
    raise ImportError

# XX TODO: is this a good number? who knows... it does match the default Linux
# pipe capacity though.
DEFAULT_RECEIVE_SIZE = 65536


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
        self._original_is_blocking = os.get_blocking(fd)
        os.set_blocking(fd, False)

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
        os.set_blocking(fd, self._original_is_blocking)
        os.close(fd)

    def __del__(self):
        self._raw_close()

    async def aclose(self):
        if not self.closed:
            trio.hazmat.notify_closing(self.fd)
            self._raw_close()
        await trio.hazmat.checkpoint()


class FdStream(Stream):
    """
    Represents a stream given the file descriptor to a pipe, TTY, etc.

    *fd* must refer to a file that is open for reading and/or writing and
    supports non-blocking I/O (pipes and TTYs will work, on-disk files probably
    not).  The returned stream takes ownership of the fd, so closing the stream
    will close the fd too.  As with `os.fdopen`, you should not directly use
    an fd after you have wrapped it in a stream using this function.

    To be used as a Trio stream, an open file must be placed in non-blocking
    mode.  Unfortunately, this impacts all I/O that goes through the
    underlying open file, including I/O that uses a different
    file descriptor than the one that was passed to Trio. If other threads
    or processes are using file descriptors that are related through `os.dup`
    or inheritance across `os.fork` to the one that Trio is using, they are
    unlikely to be prepared to have non-blocking I/O semantics suddenly
    thrust upon them.  For example, you can use ``FdStream(os.dup(0))`` to
    obtain a stream for reading from standard input, but it is only safe to
    do so with heavy caveats: your stdin must not be shared by any other
    processes and you must not make any calls to synchronous methods of
    `sys.stdin` until the stream returned by `FdStream` is closed. See
    `issue #174 <https://github.com/python-trio/trio/issues/174>`__ for a
    discussion of the challenges involved in relaxing this restriction.

    The Unix file descriptor API does not provide any generic way to perform a
    half-close, so ``FdStream.send_eof`` always raises `NotImplementedError`.

    Args:
      fd (int): The fd to be wrapped.

    Returns:
      A new `FdStream` object.
    """
    def __init__(self, fd: int):
        self._fd_holder = _FdHolder(fd)
        self._send_conflict_detector = ConflictDetector(
            "another task is using this stream for send"
        )
        self._receive_conflict_detector = ConflictDetector(
            "another task is using this stream for receive"
        )

    async def send_all(self, data: bytes):
        with self._send_conflict_detector:
            # have to check up front, because send_all(b"") on a closed pipe
            # should raise
            if self._fd_holder.closed:
                raise trio.ClosedResourceError("file was already closed")
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
                                    "file was already closed"
                                ) from None
                            else:
                                raise trio.BrokenResourceError from e

    async def wait_send_all_might_not_block(self) -> None:
        with self._send_conflict_detector:
            if self._fd_holder.closed:
                raise trio.ClosedResourceError("file was already closed")
            try:
                await trio.hazmat.wait_writable(self._fd_holder.fd)
            except BrokenPipeError as e:
                # kqueue: raises EPIPE on wait_writable instead
                # of sending, which is annoying
                raise trio.BrokenResourceError from e

    async def receive_some(self, max_bytes=None) -> bytes:
        with self._receive_conflict_detector:
            if max_bytes is None:
                max_bytes = DEFAULT_RECEIVE_SIZE
            else:
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
                            "file was already closed"
                        ) from None
                    else:
                        raise trio.BrokenResourceError from e
                else:
                    break

            return data

    async def send_eof(self):
        raise NotImplementedError

    async def aclose(self):
        await self._fd_holder.aclose()

    def fileno(self):
        return self._fd_holder.fd
