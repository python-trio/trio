from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import trio
import trio.socket as tsocket
from trio import TaskStatus

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


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
# https://github.com/python-trio/trio/wiki/notes-to-self#measure-listen-backlogpy
def _compute_backlog(backlog: int | None) -> int:
    # Many systems (Linux, BSDs, ...) store the backlog in a uint16 and are
    # missing overflow protection, so we apply our own overflow protection.
    # https://github.com/golang/go/issues/5030
    if not isinstance(backlog, int) and backlog is not None:
        raise TypeError(f"backlog must be an int or None, not {backlog!r}")
    if backlog is None:
        return 0xFFFF
    return min(backlog, 0xFFFF)


async def open_unix_listener(
    path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    *,
    mode: int | None = None,  # 0o666,
    backlog: int | None = None,
) -> trio.UnixSocketListener:
    """Create :class:`SocketListener` objects to listen for  connections.
    Opens a connection to the specified
    `Unix domain socket <https://en.wikipedia.org/wiki/Unix_domain_socket>`__.

    You must have read/write permission on the specified file to connect.

    Args:

      path (str): Filename of UNIX socket to create and listen on.
          Absolute or relative paths may be used.

      mode (int or None): The socket file permissions.
          UNIX permissions are usually specified in octal numbers.
          If you leave this as ``None``, Trio will not change the mode from
          the operating system's default.

      backlog (int or None): The listen backlog to use. If you leave this as
          ``None`` then Trio will pick a good default. (Currently: whatever
          your system has configured as the maximum backlog.)

    Returns:
      :class:`UnixSocketListener`

    Raises:
      :class:`TypeError` if invalid arguments.
      :class:`RuntimeError`: If AF_UNIX sockets are not supported.
    """
    if not HAS_UNIX:
        raise RuntimeError("Unix sockets are not supported on this platform")

    computed_backlog = _compute_backlog(backlog)

    fspath = await trio.Path(os.fsdecode(path)).absolute()

    folder = fspath.parent
    if not await folder.exists():
        raise FileNotFoundError(f"Socket folder does not exist: {folder!r}")

    # much more simplified logic vs tcp sockets - one socket type and only one
    # possible location to connect to
    sock = tsocket.socket(AF_UNIX, tsocket.SOCK_STREAM)
    try:
        # See https://github.com/python-trio/trio/issues/39
        if sys.platform != "win32":
            sock.setsockopt(tsocket.SOL_SOCKET, tsocket.SO_REUSEADDR, 1)

        await sock.bind(str(fspath))

        sock.listen(computed_backlog)

        if mode is not None:
            await fspath.chmod(mode)

        return trio.UnixSocketListener(sock)
    except BaseException as exc:
        sock.close()
        try:
            os.unlink(str(fspath))
        except BaseException as exc_2:
            raise exc_2 from exc
        raise


async def serve_unix(
    handler: Callable[[trio.SocketStream], Awaitable[object]],
    path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    *,
    backlog: int | None = None,
    handler_nursery: trio.Nursery | None = None,
    task_status: TaskStatus[list[trio.UnixSocketListener]] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Listen for incoming UNIX connections, and for each one start a task
    running ``handler(stream)``.
    This is a thin convenience wrapper around :func:`open_unix_listener` and
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
          Passed to :func:`open_unix_listener`.
      backlog: The listen backlog, or None to have a good default picked.
          Passed to :func:`open_tcp_listener`.
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

    listener = await open_unix_listener(path, backlog=backlog)
    await trio.serve_listeners(
        handler,
        [listener],
        handler_nursery=handler_nursery,
        task_status=task_status,
    )
