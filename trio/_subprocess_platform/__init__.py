# Platform-specific subprocess bits'n'pieces.

import os
from typing import Tuple

from .. import _core, _subprocess
from .._abc import SendStream, ReceiveStream


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
    raise NotImplementedError from wait_child_exiting._error  # pragma: no cover


def create_pipe_to_child_stdin() -> Tuple[SendStream, int]:
    """Create a new pipe suitable for sending data from this
    process to the standard input of a child we're about to spawn.

    Returns:
      A pair ``(trio_end, subprocess_end)`` where ``trio_end`` is a
      :class:`~trio.abc.SendStream` and ``subprocess_end`` is
      something suitable for passing as the ``stdin`` argument of
      :class:`subprocess.Popen`.
    """
    raise NotImplementedError from (  # pragma: no cover
        create_pipe_to_child_stdin._error
    )


def create_pipe_from_child_output() -> Tuple[ReceiveStream, int]:
    """Create a new pipe suitable for receiving data into this
    process from the standard output or error stream of a child
    we're about to spawn.

    Returns:
      A pair ``(trio_end, subprocess_end)`` where ``trio_end`` is a
      :class:`~trio.abc.ReceiveStream` and ``subprocess_end`` is
      something suitable for passing as the ``stdin`` argument of
      :class:`subprocess.Popen`.
    """
    raise NotImplementedError from (  # pragma: no cover
        create_pipe_to_child_stdin._error
    )


try:
    if os.name == "nt":
        from .windows import wait_child_exiting  # noqa: F811
    elif hasattr(_core, "wait_kevent"):
        from .kqueue import wait_child_exiting  # noqa: F811
    else:
        from .waitid import wait_child_exiting  # noqa: F811
except ImportError as ex:  # pragma: no cover
    wait_child_exiting._error = ex

try:
    if os.name == "posix":
        from ..hazmat import FdStream

        def create_pipe_to_child_stdin():  # noqa: F811
            rfd, wfd = os.pipe()
            return FdStream(wfd), rfd

        def create_pipe_from_child_output():  # noqa: F811
            rfd, wfd = os.pipe()
            return FdStream(rfd), wfd

    elif os.name == "nt":
        from .._windows_pipes import PipeSendStream, PipeReceiveStream

        # This isn't exported or documented, but it's also not
        # underscore-prefixed, and seems kosher to use. The asyncio docs
        # for 3.5 included an example that imported socketpair from
        # windows_utils (before socket.socketpair existed on Windows), and
        # when asyncio.windows_utils.socketpair was removed in 3.7, the
        # removal was mentioned in the release notes.
        from asyncio.windows_utils import pipe as windows_pipe
        import msvcrt

        def create_pipe_to_child_stdin():  # noqa: F811
            # for stdin, we want the write end (our end) to use overlapped I/O
            rh, wh = windows_pipe(overlapped=(False, True))
            return PipeSendStream(wh), msvcrt.open_osfhandle(rh, os.O_RDONLY)

        def create_pipe_from_child_output():  # noqa: F811
            # for stdout/err, it's the read end that's overlapped
            rh, wh = windows_pipe(overlapped=(True, False))
            return PipeReceiveStream(rh), msvcrt.open_osfhandle(wh, 0)

    else:  # pragma: no cover
        raise ImportError("pipes not implemented on this platform")

except ImportError as ex:  # pragma: no cover
    create_pipe_to_child_stdin._error = ex
    create_pipe_from_child_output._error = ex
