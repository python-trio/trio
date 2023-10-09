# ***********************************************************
# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******
# *************************************************************
from __future__ import annotations

from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED
from ._run import GLOBAL_RUN_CONTEXT
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .._file_io import _HasFileNo
import sys

assert not TYPE_CHECKING or sys.platform == "linux"


async def wait_readable(fd: (int | _HasFileNo)) -> None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_readable(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def wait_writable(fd: (int | _HasFileNo)) -> None:
    """Block until the kernel reports that the given object is writable.

    See `wait_readable` for the definition of ``obj``.

    :raises trio.BusyResourceError:
        if another task is already waiting for the given socket to
        become writable.
    :raises trio.ClosedResourceError:
        if another task calls :func:`notify_closing` while this
        function is still working.
    """
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_writable(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context")


def notify_closing(fd: (int | _HasFileNo)) -> None:
    """Call this before closing a file descriptor (on Unix) or socket (on
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
        return GLOBAL_RUN_CONTEXT.runner.io_manager.notify_closing(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context")
