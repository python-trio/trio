# "High-level" networking interface

import os
import fcntl
import errno

from .. import _core
from .._util import ConflictDetector
from ..abc import SendStream, ReceiveStream, AsyncResource

__all__ = ["ReadFDStream", "WriteFDStream"]

_closed_stream_errnos = {
    # Unix
    errno.EBADF,
    # Windows
    errno.ENOTSOCK,
}

class _FDStream(AsyncResource):
    def __init__(self, fd):
        if hasattr(fd,'fileno'):
            # Unwrap Python's IO buffers.
            while hasattr(fd,'detach'):
                fd = fd.detach()
            # _io.FileIO.closefd is not writeable and we don't want to hold
            # a reference to the original file descriptor, so take the easy
            # way out
            fd = os.dup(fd.fileno())
        if not isinstance(fd, int) or fd < 0:
            raise TypeError("ReadFDStream requires a file descriptor")

        self._fd = fd
        self._fdflags = fcntl.fcntl(fd, fcntl.F_GETFL, 0)
        fcntl.fcntl(fd, fcntl.F_SETFL, self._fdflags | os.O_NONBLOCK)
        
        self._send_conflict_detector = ConflictDetector(
            "another task is currently sending data to this ReadFDStream"
        )

    def fileno(self):
        return self._fd

    async def aclose(self):
        self.close()
        await _core.checkpoint()

    def close(self):
        try:
            #fcntl.fcntl(self._fd, fcntl.F_SETFL, self._fdflags)
            os.close(self._fd)
        except OSError as err:
            if err.errno != errno.EBADF:
                raise


class ReadFDStream(_FDStream, ReceiveStream):
    """An implementation of the :class:`trio.abc.ReceiveStream`
    interface based on a raw file descriptor.

    Args:
      fd: The file descriptor to wrap.

    The file descriptor will *not* be closed by this object's :meth:`close`
    or :meth:`aclose` methods.
    """

    async def receive_some(self, max_bytes):
        if max_bytes < 1:
            await _core.checkpoint()
            raise ValueError("max_bytes must be >= 1")
        await _core.wait_readable(self._fd)
        return os.read(self._fd, max_bytes)


class WriteFDStream(_FDStream, SendStream):
    """An implementation of the :class:`trio.abc.SendStream`
    interface based on a raw file descriptor.

    Args:
      fd: The file descriptor to wrap.

    The file descriptor will *not* be closed by this object's :meth:`close`
    or :meth:`aclose` methods.
    """

    async def send_all(self, data):
        with self._send_conflict_detector.sync:
            with memoryview(data) as data:
                if not data:
                    await _core.checkpoint()
                    return
                total_sent = 0
                while total_sent < len(data):
                    with data[total_sent:] as remaining:
                        await _core.wait_writable(self._fd)
                        sent = os.write(self._fd, remaining)
                    total_sent += sent

    async def wait_send_all_might_not_block(self):
        async with self._send_conflict_detector:
            await self.socket.wait_writable()

