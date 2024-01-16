# ***********************************************************
# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******
# *************************************************************
from __future__ import annotations

from typing import TYPE_CHECKING, ContextManager

from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED
from ._run import GLOBAL_RUN_CONTEXT

if TYPE_CHECKING:
    from typing_extensions import Buffer

    from .._channel import MemoryReceiveChannel
    from .._file_io import _HasFileNo
    from ._windows_cffi import CData, Handle
import sys

assert not TYPE_CHECKING or sys.platform == "win32"


__all__ = [
    "current_iocp",
    "monitor_completion_key",
    "notify_closing",
    "readinto_overlapped",
    "register_with_iocp",
    "wait_overlapped",
    "wait_readable",
    "wait_writable",
    "write_overlapped",
]


async def wait_readable(sock: (_HasFileNo | int)) -> None:
    """Block until the kernel reports that the given object is readable.

    On Unix systems, ``sock`` must either be an integer file descriptor,
    or else an object with a ``.fileno()`` method which returns an
    integer file descriptor. Any kind of file descriptor can be passed,
    though the exact semantics will depend on your kernel. For example,
    this probably won't do anything useful for on-disk files.

    On Windows systems, ``sock`` must either be an integer ``SOCKET``
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
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_readable(sock)
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


async def wait_writable(sock: (_HasFileNo | int)) -> None:
    """Block until the kernel reports that the given object is writable.

    See `wait_readable` for the definition of ``sock``.

    :raises trio.BusyResourceError:
        if another task is already waiting for the given socket to
        become writable.
    :raises trio.ClosedResourceError:
        if another task calls :func:`notify_closing` while this
        function is still working.
    """
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_writable(sock)
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


def notify_closing(handle: (Handle | int | _HasFileNo)) -> None:
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
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.notify_closing(handle)
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


def register_with_iocp(handle: (int | CData)) -> None:
    """TODO: these are implemented, but are currently more of a sketch than
    anything real. See `#26
    <https://github.com/python-trio/trio/issues/26>`__ and `#52
    <https://github.com/python-trio/trio/issues/52>`__.
    """
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.register_with_iocp(handle)
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


async def wait_overlapped(
    handle_: (int | CData), lpOverlapped: (CData | int)
) -> object:
    """TODO: these are implemented, but are currently more of a sketch than
    anything real. See `#26
    <https://github.com/python-trio/trio/issues/26>`__ and `#52
    <https://github.com/python-trio/trio/issues/52>`__.
    """
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_overlapped(
            handle_, lpOverlapped
        )
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


async def write_overlapped(
    handle: (int | CData), data: Buffer, file_offset: int = 0
) -> int:
    """TODO: these are implemented, but are currently more of a sketch than
    anything real. See `#26
    <https://github.com/python-trio/trio/issues/26>`__ and `#52
    <https://github.com/python-trio/trio/issues/52>`__.
    """
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.write_overlapped(
            handle, data, file_offset
        )
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


async def readinto_overlapped(
    handle: (int | CData), buffer: Buffer, file_offset: int = 0
) -> int:
    """TODO: these are implemented, but are currently more of a sketch than
    anything real. See `#26
    <https://github.com/python-trio/trio/issues/26>`__ and `#52
    <https://github.com/python-trio/trio/issues/52>`__.
    """
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.readinto_overlapped(
            handle, buffer, file_offset
        )
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


def current_iocp() -> int:
    """TODO: these are implemented, but are currently more of a sketch than
    anything real. See `#26
    <https://github.com/python-trio/trio/issues/26>`__ and `#52
    <https://github.com/python-trio/trio/issues/52>`__.
    """
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.current_iocp()
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


def monitor_completion_key() -> (
    ContextManager[tuple[int, MemoryReceiveChannel[object]]]
):
    """TODO: these are implemented, but are currently more of a sketch than
    anything real. See `#26
    <https://github.com/python-trio/trio/issues/26>`__ and `#52
    <https://github.com/python-trio/trio/issues/52>`__.
    """
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.monitor_completion_key()
    except AttributeError:
        raise RuntimeError("must be called from async context") from None
