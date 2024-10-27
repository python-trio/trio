# ***********************************************************
# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******
# *************************************************************
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from ._ki import enable_ki_protection
from ._run import GLOBAL_RUN_CONTEXT

if TYPE_CHECKING:
    import select
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from .. import _core
    from .._file_io import _HasFileNo
    from ._traps import Abort, RaiseCancelT

assert not TYPE_CHECKING or sys.platform == "darwin"


__all__ = [
    "current_kqueue",
    "monitor_kevent",
    "notify_closing",
    "wait_kevent",
    "wait_readable",
    "wait_writable",
]


@enable_ki_protection
def current_kqueue() -> select.kqueue:
    """TODO: these are implemented, but are currently more of a sketch than
    anything real. See `#26
    <https://github.com/python-trio/trio/issues/26>`__.
    """
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.current_kqueue()
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


@enable_ki_protection
def monitor_kevent(
    ident: int,
    filter: int,
) -> AbstractContextManager[_core.UnboundedQueue[select.kevent]]:
    """TODO: these are implemented, but are currently more of a sketch than
    anything real. See `#26
    <https://github.com/python-trio/trio/issues/26>`__.
    """
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.monitor_kevent(ident, filter)
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


@enable_ki_protection
async def wait_kevent(
    ident: int,
    filter: int,
    abort_func: Callable[[RaiseCancelT], Abort],
) -> Abort:
    """TODO: these are implemented, but are currently more of a sketch than
    anything real. See `#26
    <https://github.com/python-trio/trio/issues/26>`__.
    """
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_kevent(
            ident,
            filter,
            abort_func,
        )
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


@enable_ki_protection
async def wait_readable(fd: int | _HasFileNo) -> None:
    """Block until the kernel reports that the given object is readable.

    On Unix systems, ``fd`` must either be an integer file descriptor,
    or else an object with a ``.fileno()`` method which returns an
    integer file descriptor. Any kind of file descriptor can be passed,
    though the exact semantics will depend on your kernel. For example,
    this probably won't do anything useful for on-disk files.

    On Windows systems, ``fd`` must either be an integer ``SOCKET``
    handle, or else an object with a ``.fileno()`` method which returns
    an integer ``SOCKET`` handle. File descriptors aren't supported,
    and neither are handles that refer to anything besides a
    ``SOCKET``.

    :raises trio.BusyResourceError:
        if another task is already waiting for the given socket to
        become readable.
    :raises trio.ClosedResourceError:
        if another task calls :func:`notify_closing` while this
        function is still working.
    """
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_readable(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


@enable_ki_protection
async def wait_writable(fd: int | _HasFileNo) -> None:
    """Block until the kernel reports that the given object is writable.

    See `wait_readable` for the definition of ``fd``.

    :raises trio.BusyResourceError:
        if another task is already waiting for the given socket to
        become writable.
    :raises trio.ClosedResourceError:
        if another task calls :func:`notify_closing` while this
        function is still working.
    """
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_writable(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


@enable_ki_protection
def notify_closing(fd: int | _HasFileNo) -> None:
    """Notify waiters of the given object that it will be closed.

    Call this before closing a file descriptor (on Unix) or socket (on
    Windows). This will cause any `wait_readable` or `wait_writable`
    calls on the given object to immediately wake up and raise
    `~trio.ClosedResourceError`.

    This doesn't actually close the object – you still have to do that
    yourself afterwards. Also, you want to be careful to make sure no
    new tasks start waiting on the object in between when you call this
    and when it's actually closed. So to close something properly, you
    usually want to do these steps in order:

    1. Explicitly mark the object as closed, so that any new attempts
       to use it will abort before they start.
    2. Call `notify_closing` to wake up any already-existing users.
    3. Actually close the object.

    It's also possible to do them in a different order if that's more
    convenient, *but only if* you make sure not to have any checkpoints in
    between the steps. This way they all happen in a single atomic
    step, so other tasks won't be able to tell what order they happened
    in anyway.
    """
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.notify_closing(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context") from None
