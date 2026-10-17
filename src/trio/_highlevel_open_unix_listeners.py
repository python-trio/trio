from __future__ import annotations

import os
import secrets
import stat
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, NoReturn

import trio
import trio.socket as tsocket

from ._highlevel_socket import (
    SocketStream,
    _closed_stream_errnos,
    _ignorable_accept_errnos,
)
from ._util import final
from .abc import Listener

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator

    from typing_extensions import Self

    from ._socket import _SocketType as SocketType


try:
    from trio.socket import AF_UNIX

    HAS_UNIX = True
except ImportError:
    HAS_UNIX = False


# Default backlog size:
#
# Having the backlog too low can cause practical problems (a perfectly healthy
# service that starts failing to accept connections if they arrive in a
# burst).
#
# Having it too high doesn't really cause any problems. Like any buffer, you
# want backlog queue to be zero usually, and it won't save you if you're
# getting connection attempts faster than you can call accept() on an ongoing
# basis. But unlike other buffers, this one doesn't really provide any
# backpressure. If a connection gets stuck waiting in the backlog queue, then
# from the peer's point of view the connection succeeded but then their
# send/recv will stall until we get to it, possibly for a long time. OTOH if
# there isn't room in the backlog queue, then their connect stalls, possibly
# for a long time, which is pretty much the same thing.
#
# A large backlog can also use a bit more kernel memory, but this seems fairly
# negligible these days.
#
# So this suggests we should make the backlog as large as possible. This also
# matches what Golang does. However, they do it in a weird way, where they
# have a bunch of code to sniff out the configured upper limit for backlog on
# different operating systems. But on every system, passing in a too-large
# backlog just causes it to be silently truncated to the configured maximum,
# so this is unnecessary -- we can just pass in "infinity" and get the maximum
# that way. (Verified on Windows, Linux, macOS using
# notes-to-self/measure-listen-backlog.py)
def _compute_backlog(backlog: int | None) -> int:
    # Many systems (Linux, BSDs, ...) store the backlog in a uint16 and are
    # missing overflow protection, so we apply our own overflow protection.
    # https://github.com/golang/go/issues/5030
    if backlog is None:
        return 0xFFFF
    return min(backlog, 0xFFFF)


def _inode(
    filename: int | str | bytes | os.PathLike[str] | os.PathLike[bytes],
) -> tuple[int, int]:
    """Return a (dev, inode) tuple uniquely identifying a file."""
    stat = os.stat(filename)
    return stat.st_dev, stat.st_ino


@contextmanager
def _lock(
    socketname: str | bytes | os.PathLike[str] | os.PathLike[bytes],
) -> Generator[None, None, None]:
    """Protect socketname access by a lock file."""
    name: str | bytes
    if isinstance(socketname, bytes):
        name = socketname + b".lock"
    else:
        name = f"{socketname}.lock"
    start_monotonic = time.monotonic()
    # Atomically acquire the lock file
    while True:
        try:
            os.close(os.open(name, os.O_CREAT | os.O_EXCL))
            break  # Lock file created!
        except FileExistsError:
            pass
        # Retry but avoid busy polling
        time.sleep(0.01)
        try:
            ctime = os.stat(name).st_ctime
            if ctime and abs(time.time() - ctime) > 2.0:
                raise FileExistsError(f"Stale lock file {name!r}")
        except FileNotFoundError:
            pass
        if time.monotonic() - start_monotonic > 1.0:
            raise FileExistsError(f"Timeout acquiring {name!r}")
    try:
        yield
    finally:
        os.unlink(name)


@final
class UnixSocketListener(Listener[SocketStream]):
    """A :class:`~trio.abc.Listener` that uses a listening socket to accept
    incoming connections as :class:`SocketStream` objects.

    Args:
      socket: The Trio socket object to wrap. Must have type ``SOCK_STREAM``,
          and be listening.
      path: The path the unix socket is bound too.
      inode: (dev, inode) tuple uniquely identifying the socket file.

    Note that the :class:`UnixSocketListener` "takes ownership" of the given
    socket; closing the :class:`UnixSocketListener` will also close the socket.

    .. attribute:: socket

       The Trio socket object that this stream wraps.

    """

    __slots__ = ("inode", "path", "socket")

    def __init__(
        self,
        socket: SocketType,
        path: str,
        inode: tuple[int, int],
    ) -> None:
        """Private constructor. Use UnixSocketListener.create instead."""
        if not HAS_UNIX:
            raise RuntimeError("Unix sockets are not supported on this platform")
        if not isinstance(socket, tsocket.SocketType):
            raise TypeError("UnixSocketListener requires a Trio socket object")
        if socket.type != tsocket.SOCK_STREAM:
            raise ValueError("UnixSocketListener requires a SOCK_STREAM socket")
        try:
            listening = socket.getsockopt(tsocket.SOL_SOCKET, tsocket.SO_ACCEPTCONN)
        except OSError:
            # SO_ACCEPTCONN fails on macOS; we just have to trust the user.
            pass
        else:
            if not listening:
                raise ValueError("UnixSocketListener requires a listening socket")

        self.socket = socket
        self.path = path
        self.inode = inode

    @classmethod
    async def _create(
        cls,
        path: str | bytes,
        mode: int,
        backlog: int,
    ) -> Self:
        # Sanitise and pre-verify socket path
        if not isinstance(path, str):
            path = path.decode("utf-8")
        path = os.path.abspath(path)
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            raise FileNotFoundError(f"Socket folder does not exist: {folder!r}")
        try:
            if not stat.S_ISSOCK(os.stat(path, follow_symlinks=False).st_mode):
                raise FileExistsError(f"Existing file is not a socket: {path!r}")
        except FileNotFoundError:
            pass
        # Create new socket with a random temporary name
        tmp_path = f"{path}.{secrets.token_urlsafe()}"
        sock = tsocket.socket(AF_UNIX, tsocket.SOCK_STREAM)
        try:
            # Critical section begins (filename races)
            await sock.bind(tmp_path)
            try:
                inode = _inode(tmp_path)
                os.chmod(tmp_path, mode)
                # Start listening before rename to avoid connection failures
                sock.listen(backlog)
                # Replace the requested name (atomic overwrite if necessary)
                with _lock(path):
                    os.rename(tmp_path, path)
                return cls(sock, path, inode)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                finally:
                    raise
        except BaseException:
            try:
                sock.close()
            finally:
                raise

    @classmethod
    async def create(
        cls,
        path: str | bytes,
        *,
        mode: int = 0o666,
        backlog: int | None = None,
    ) -> Self:
        """Create new unix socket listener.

        Args:
          path (str, bytes): Path to folder where new socket file will be created.

          mode (int): Unix octal file mode of new socket file.

          backlog (int or None): The listen backlog to use. If you leave this as
              ``None`` then Trio will pick a good default. (Currently: whatever
              your system has configured as the maximum backlog.)

        Returns:
          :class:`UnixSocketListener`

        Raises:
          FileNotFoundError: if socket path doesn't exist
          FileExistsError: if existing file is not a socket

        """
        backlog = _compute_backlog(backlog)
        return await cls._create(path=path, mode=mode, backlog=backlog or 0xFFFF)

    def _close(self) -> None:
        try:
            # Verify that the socket hasn't been replaced by another instance
            # before unlinking. Needs locking to prevent another instance of
            # this program replacing it between stat and unlink.
            with _lock(self.path):
                if self.inode == _inode(self.path):
                    os.unlink(self.path)
        except OSError:
            pass

    async def accept(self) -> SocketStream:
        """Accept an incoming connection.

        Returns:
          :class:`SocketStream`

        Raises:
          OSError: if the underlying call to ``accept`` raises an unexpected
              error.
          ClosedResourceError: if you already closed the socket.

        This method handles routine errors like ``ECONNABORTED``, but passes
        other errors on to its caller. In particular, it does *not* make any
        special effort to handle resource exhaustion errors like ``EMFILE``,
        ``ENFILE``, ``ENOBUFS``, ``ENOMEM``.

        """
        while True:
            try:
                sock, _ = await self.socket.accept()
            except OSError as exc:
                if exc.errno in _closed_stream_errnos:
                    raise trio.ClosedResourceError from None
                if exc.errno not in _ignorable_accept_errnos:
                    raise
            else:
                return SocketStream(sock)

    async def aclose(self) -> None:
        """Close this listener and its underlying socket."""
        with trio.fail_after(10) as cleanup:
            cleanup.shield = True
            self.socket.close()
            await trio.lowlevel.checkpoint()
            await trio.to_thread.run_sync(self._close)


async def open_unix_listeners(
    path: str | bytes,
    *,
    mode: int = 0o666,
    backlog: int | None = None,
) -> list[UnixSocketListener]:
    """Create :class:`UnixSocketListener` objects to listen for UNIX connections.

    Args:

      path (str): Filename of UNIX socket to create and listen on.

          Absolute or relative paths may be used.

          The socket is initially created with a random token appended to its
          name, and then moved over the requested name while protected by a
          separate lock file. The additional names use suffixes on the
          requested name.

      mode (int): The socket file permissions.

          UNIX permissions are usually specified in octal numbers.

          The default mode 0o666 gives user, group and other read and write
          permissions, allowing connections from anyone on the system.

      backlog (int or None): The listen backlog to use. If you leave this as
          ``None`` then Trio will pick a good default. (Currently: whatever
          your system has configured as the maximum backlog.)

    Returns:
      list of :class:`UnixSocketListener`

    Raises:
      RuntimeError: If AF_UNIX sockets are not supported.

    """
    if not HAS_UNIX:
        raise RuntimeError("Unix sockets are not supported on this platform")

    return [await UnixSocketListener.create(path, mode=mode, backlog=backlog)]


async def serve_unix(
    handler: Callable[[trio.SocketStream], Awaitable[object]],
    path: str | bytes,
    *,
    backlog: int | None = None,
    handler_nursery: trio.Nursery | None = None,
    task_status: trio.TaskStatus[list[UnixSocketListener]] = trio.TASK_STATUS_IGNORED,
) -> NoReturn:
    """Listen for incoming UNIX connections, and for each one start a task
    running ``handler(stream)``.

    This is a thin convenience wrapper around :func:`open_unix_listeners` and
    :func:`serve_listeners` – see them for full details.

    .. warning::

       If ``handler`` raises an exception, then this function doesn't do
       anything special to catch it – so by default the exception will
       propagate out and crash your server. If you don't want this, then catch
       exceptions inside your ``handler``, or use a ``handler_nursery`` object
       that responds to exceptions in some other way.

    When used with ``nursery.start`` you get back the newly opened listeners.

    Args:
      handler: The handler to start for each incoming connection. Passed to
          :func:`serve_listeners`.

      path: The socket file name.
          Passed to :func:`open_unix_listeners`.

      backlog: The listen backlog, or None to have a good default picked.
          Passed to :func:`open_tcp_listeners`.

      handler_nursery: The nursery to start handlers in, or None to use an
          internal nursery. Passed to :func:`serve_listeners`.

      task_status: This function can be used with ``nursery.start``.

    Returns:
      This function only returns when cancelled.

    Raises:
      RuntimeError: If AF_UNIX sockets are not supported.

    """
    if not HAS_UNIX:
        raise RuntimeError("Unix sockets are not supported on this platform")

    listeners = await open_unix_listeners(path, backlog=backlog)
    await trio.serve_listeners(
        handler, listeners, handler_nursery=handler_nursery, task_status=task_status
    )
