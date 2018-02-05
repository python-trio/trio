import os
import sys
import signal
import threading
import weakref
import subprocess
from contextlib import contextmanager

try:
    import signalfd
except ImportError:
    signalfd = None

from .. import _core
from .. import _sync

__all__ = ['wait_for_child']

# TODO: use whatever works for Windows and MacOS/BSD

_children = weakref.WeakValueDictionary()

def _compute_returncode(status):
    if os.WIFSIGNALED(status):
        # The child process died because of a signal.
        return -os.WTERMSIG(status)
    elif os.WIFEXITED(status):
        # The child process exited (e.g sys.exit()).
        return os.WEXITSTATUS(status)
    elif os.WIFSTOPPED(sts):
        return -os.WSTOPSIG(status)
    else:
        # This shouldn't happen.
        raise UnknownStatus(pid, status)

NOT_FOUND_VALUE = _core.Error(ChildProcessError())

class ProcessWaiter:
    """I implement waiting for a child process."""

    __token = None
    __event = None
    __pid = None
    __result = None
    __thread = None

    def __new__(cls, pid=None):
        """Grab an existing object if there is one"""
        self = _children.get(pid, None)
        if self is None:
            self = object.__new__(cls)
        return self

    def __init__(self, pid=None):
        if self.__pid is None:
            self._set_pid(pid)

    def _set_pid(self, pid):
        if self.__pid is not None:
            raise RuntimeError("You can't change the pid")
        if not isinstance(pid, int):
            raise RuntimeError("a PID needs to be an integer")

        self.__pid = pid
        _children[pid] = self

    async def wait(self):
        """Wait for this child process to end."""
        if self.__result is None:
            if self.__pid is None:
                raise RuntimeError("I don't know what to wait for!")

            # Check once, before doing the heavy lifting
            self._wait_pid(blocking=False)
            if self.__result is None:
                if self.__thread is None:
                    await self._start_waiting()
                await self.__event.wait()
        return self.__result.unwrap()

    async def _start_waiting(self):
        """Start the background thread that waits for a specific child"""
        self.__event = _sync.Event()
        self.__token = _core.current_trio_token()

        self.__thread = threading.Thread(target=self._wait_thread, daemon=True)
        self.__thread.start()

    def _wait_thread(self):
        """The background thread that waits for a specific child"""
        self._wait_pid(blocking=True)
        self.__token.run_sync_soon(self.__event.set)

    def _wait_pid(self, blocking):
        """check up on a child process"""
        assert self.__pid > 0

        try:
            pid, status = os.waitpid(self.__pid, 0 if blocking else os.WNOHANG)
        except ChildProcessError:
            # The child process may already be reaped
            # (may happen if waitpid() is called elsewhere).
            self.__result = NOT_FOUND
        else:
            if pid == 0:
                # The child process is still alive.
                return
            del _children[pid]
            self._handle_exitstatus(status)

    def _handle_exitstatus(self, sts):
        """This overrides an internal API of subprocess.Popen"""
        self.__result = _core.Result.capture(_compute_returncode,sts)

    @property
    def returncode(self):
        if self.__result is None:
            return None
        return self.__result.unwrap()

    @returncode.setter
    def returncode(self, result):
        if result is not None:
            raise RuntimeError("We should not get here.")
        if self.__result is not None:
            raise RuntimeError("You cannot reset the result code.")

async def wait_for_child(pid):
    waiter = ProcessWaiter(pid)
    return await waiter.wait()

