# Platform-specific subprocess bits'n'pieces.

import sys
from typing import TYPE_CHECKING, Optional, Tuple

from .. import _core, _subprocess

_wait_child_exiting_error: Optional[ImportError] = None
_create_child_pipe_error: Optional[ImportError] = None


if TYPE_CHECKING:
    # internal types for the pipe representations used in type checking only
    from .._abc import ReceiveStream, SendStream

    class ClosableSendStream(SendStream):
        def close(self) -> None:
            ...

    class ClosableReceiveStream(ReceiveStream):
        def close(self) -> None:
            ...


# Fallback versions of the functions provided -- implementations
# per OS are imported atop these at the bottom of the module.
async def wait_child_exiting(process: "_subprocess.Process") -> None:
    """Block until the child process managed by ``process`` is exiting.

    It is invalid to call this function if the process has already
    been waited on; that is, ``process.returncode`` must be None.

    When this function returns, it indicates that a call to
    :meth:`subprocess.Popen.wait` will immediately be able to
    return the process's exit status. The actual exit status is not
    consumed by this call, since :class:`~subprocess.Popen` wants
    to be able to do that itself.
    """
    raise NotImplementedError from _wait_child_exiting_error  # pragma: no cover


def create_pipe_to_child_stdin() -> Tuple["ClosableSendStream", int]:
    """Create a new pipe suitable for sending data from this
    process to the standard input of a child we're about to spawn.

    Returns:
      A pair ``(trio_end, subprocess_end)`` where ``trio_end`` is a
      :class:`~trio.abc.SendStream` and ``subprocess_end`` is
      something suitable for passing as the ``stdin`` argument of
      :class:`subprocess.Popen`.
    """
    raise NotImplementedError from _create_child_pipe_error  # pragma: no cover


def create_pipe_from_child_output() -> Tuple["ClosableReceiveStream", int]:
    """Create a new pipe suitable for receiving data into this
    process from the standard output or error stream of a child
    we're about to spawn.

    Returns:
      A pair ``(trio_end, subprocess_end)`` where ``trio_end`` is a
      :class:`~trio.abc.ReceiveStream` and ``subprocess_end`` is
      something suitable for passing as the ``stdin`` argument of
      :class:`subprocess.Popen`.
    """
    raise NotImplementedError from _create_child_pipe_error  # pragma: no cover


try:
    if sys.platform == "win32":
        from .windows import wait_child_exiting  # noqa: F811
    elif sys.platform != "linux" and (TYPE_CHECKING or hasattr(_core, "wait_kevent")):
        from .kqueue import wait_child_exiting
    else:
        # as it's an exported symbol, noqa'd
        from .waitid import wait_child_exiting  # noqa: F401
except ImportError as ex:  # pragma: no cover
    _wait_child_exiting_error = ex

try:
    pass

except ImportError as ex:  # pragma: no cover
    _create_child_pipe_error = ex
