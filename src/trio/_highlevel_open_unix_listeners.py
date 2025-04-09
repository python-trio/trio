from __future__ import annotations

import os
from typing import TYPE_CHECKING

import trio
import trio.socket as tsocket
from trio import TaskStatus

from ._highlevel_open_tcp_listeners import _compute_backlog

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


try:
    from trio.socket import AF_UNIX

    HAS_UNIX = True
except ImportError:
    HAS_UNIX = False


async def open_unix_listener(
    path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    *,
    mode: int | None = None,
    backlog: int | None = None,
) -> trio.SocketListener:
    """Create :class:`SocketListener` objects to listen for  connections.
    Opens a connection to the specified
    `Unix domain socket <https://en.wikipedia.org/wiki/Unix_domain_socket>`__.

    You must have read/write permission on the specified file to connect.

    Args:

      path (str): Filename of UNIX socket to create and listen on.
          Absolute or relative paths may be used.

      mode (int or None): The socket file permissions.
          UNIX permissions are usually specified in octal numbers. If
          you leave this as ``None``, Trio will not change the mode from
          the operating system's default.

      backlog (int or None): The listen backlog to use. If you leave this as
          ``None`` then Trio will pick a good default. (Currently:
          whatever your system has configured as the maximum backlog.)

    Returns:
      :class:`UnixSocketListener`

    Raises:
      :class:`ValueError` If invalid arguments.
      :class:`RuntimeError`: If AF_UNIX sockets are not supported.
      :class:`FileNotFoundError`: If folder socket file is to be created in does not exist.
    """
    if not HAS_UNIX:
        raise RuntimeError("Unix sockets are not supported on this platform")

    computed_backlog = _compute_backlog(backlog)

    fspath = await trio.Path(os.fsdecode(path)).absolute()

    folder = fspath.parent
    if not await folder.exists():
        raise FileNotFoundError(f"Socket folder does not exist: {folder!r}")

    str_path = str(fspath)

    # much more simplified logic vs tcp sockets - one socket family and only one
    # possible location to connect to
    sock = tsocket.socket(AF_UNIX, tsocket.SOCK_STREAM)
    try:
        await sock.bind(str_path)

        if mode is not None:
            await fspath.chmod(mode)

        sock.listen(computed_backlog)

        return trio.SocketListener(sock)
    except BaseException:
        sock.close()
        if os.path.exists(str_path):
            os.unlink(str_path)
        raise


async def serve_unix(
    handler: Callable[[trio.SocketStream], Awaitable[object]],
    path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    *,
    backlog: int | None = None,
    handler_nursery: trio.Nursery | None = None,
    task_status: TaskStatus[list[trio.SocketListener]] = trio.TASK_STATUS_IGNORED,
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
