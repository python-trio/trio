# Platform-specific logic, currently mostly for subprocesses.

import os
import sys

from .. import _core


# Fallback versions of the functions provided -- implementations
# per OS are imported atop these at the bottom of the module.

async def wait_child_exiting(pid: int) -> None:
    """Block until the child process with PID ``pid`` is exiting.

    When this function returns, it indicates that a call to
    :meth:`os.waitpid` or similar is likely to immediately succeed in
    returning ``pid``'s exit status, or to immediately fail because
    ``pid`` doesn't exist. The actual exit status is not consumed;
    you need to do that yourself. (On some platforms, a wait with
    :const:`os.WNOHANG` might not succeed right away, but a blocking
    wait won't block for a noticeable amount of time.)
    """
    raise NotImplementedError from wait_child_exiting._error


try:
    if os.name == "nt":
        from .windows import wait_child_exiting
    elif hasattr(_core, "wait_kevent"):
        from .kqueue import wait_child_exiting
    else:
        from .waitid import wait_child_exiting
except ImportError as ex:
    wait_child_exiting._error = ex
