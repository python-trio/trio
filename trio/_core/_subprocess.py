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
from . import _fd_stream

import logging
logger = logging.getLogger(__name__)

__all__ = ['run_subprocess', 'wait_for_child']

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

    def __new__(cls, *args, pid=None, **kwargs):
        """Grab an existing object if there is one"""
        self = None
        if pid is not None:
            if args or kwargs:
                raise RuntimeError("'pid' is set: No other arguments allowed")
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


async def wait_for_child(pid):
    waiter = ProcessWaiter(pid)
    return await waiter.wait()

async def _close(fd):
    try:
        if fd is None:
            pass
        elif isinstance(fd,int):
            os.close(fd)
        elif hasattr(fd,'aclose'):
            await fd.aclose()
        else:
            fd.close()
    except Exception:
        logger.exception("Closing stdin: %s" % repr(fd))

class Process:
    """Start, communicate with, and wait for a subprocess.

    This class uses :class:`subprocess.Popen`. All arguments are passed
    through.

    stdin/stdout/stderr are binary Trio streams if you use ``subprocess.PIPE``.
    """

    def __init__(self, *args, **kwargs):
        if kwargs.get('universal_newlines', False):
            raise NotImplementedError("trio doesn't yet support universal_newlines")
        if kwargs.get('encoding', None) is not None or kwargs.get('errors', None) is not None:
            raise NotImplementedError("trio doesn't yet support encoding stdio")
        self._args = args
        self._kwargs = kwargs
        self._process = None
        self._waiter = None
        self.pid = None
        
    async def __aenter__(self):
        if self._process is not None:
            raise RuntimeError("You already started a process.")

        try:
            self._process = subprocess.Popen(self._args, **self._kwargs)
        except Exception as exc:
            self._waiter = _core.Error(exc)
            self.pid = None
            raise

        self.pid = self._process.pid
        self._waiter = ProcessWaiter(self.pid)

        if self._kwargs.get('stdin', None) == subprocess.PIPE:
            self.stdin = _fd_stream.WriteFDStream(self._process.stdin)
        else:
            self.stdin = self._process.stdin

        if self._kwargs.get('stdout', None) == subprocess.PIPE:
            self.stdout = _fd_stream.ReadFDStream(self._process.stdout)
        else:
            self.stdout = self._process.stdout

        if self._kwargs.get('stderr', None) == subprocess.PIPE:
            self.stderr = _fd_stream.ReadFDStream(self._process.stderr)
        else:
            self.stderr = self._process.stderr

        return self

    async def wait(self):
        return await self._waiter.wait()

    @property
    def returncode(self):
        if self._waiter is None:
            return None
        return self._waiter.returncode

    async def __aexit__(self, *tb):
        with _core.open_cancel_scope(shield=True):
            try:
                await _close(self.stdin)
                await self.wait()
                await _close(self.stdout)
                await _close(self.stderr)
            finally:
                self._process = None

    def __enter__(self):
        raise NotImplementedError("You need to use 'async with'.")

    def __exit__(self, *tb):
        raise NotImplementedError("You need to use 'async with'.")

    # override a couple methods of subprocess.Popen
    # to keep us out of danger
    def run(self, *args, **kwargs):
        raise NotImplementedError("You need to use 'async with'.")

    def communicate(self, *args, **kwargs):
        raise RuntimeError("Please use async tasks for this.")

    def _communicate(self, *args, **kwargs):
        raise RuntimeError("Please use async tasks for this.")

    def _save_input(self, input):
        raise RuntimeError("Please use async tasks for this.")

    def poll(self):
        raise NotImplementedError("You need to use 'async wait'.")

    def _internal_poll(self):
        raise RuntimeError("Please use async wait for this.")

    def __del__(self):
        # everything should have happened in __aexit__
        pass

def run_subprocess(*args, **kwargs):
    """Start a subprocess.

    See :class:`subprocess.Popen` for details.

    Example::

        with run_subprocess("/bin/echo","fubar") as proc:
            assert b"fubar\n" == await proc.stdin.receive_some(20)

    """
    return Process(*args, **kwargs)
    
