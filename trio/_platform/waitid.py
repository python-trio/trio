import math
import os

from .. import _core
from .._sync import CapacityLimiter, Event
from .._threads import run_sync_in_worker_thread

try:
    from os import waitid

    def sync_wait_reapable(pid):
        waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT)

except ImportError:
    # pypy doesn't define os.waitid so we need to pull it out ourselves
    # using cffi: https://bitbucket.org/pypy/pypy/issues/2922/
    import cffi
    waitid_ffi = cffi.FFI()

    # Believe it or not, siginfo_t starts with fields in the
    # same layout on both Linux and Darwin. The Linux structure
    # is bigger so that's what we use to size `pad`; while
    # there are a few extra fields in there, most of it is
    # true padding which would not be written by the syscall.
    waitid_ffi.cdef(
        """
typedef struct siginfo_s {
    int si_signo;
    int si_errno;
    int si_code;
    int si_pid;
    int si_uid;
    int si_status;
    int pad[26];
} siginfo_t;
int waitid(int idtype, int id, siginfo_t* result, int options);
"""
    )
    waitid = waitid_ffi.dlopen(None).waitid

    def sync_wait_reapable(pid):
        P_PID = 1
        WEXITED = 0x00000004
        if sys.platform == 'darwin':  # pragma: no cover
            # waitid() is not exposed on Python on Darwin but does
            # work through CFFI; note that we typically won't get
            # here since Darwin also defines kqueue
            WNOWAIT = 0x00000020
        else:
            WNOWAIT = 0x01000000
        result = waitid_ffi.new("siginfo_t *")
        while True:
            if waitid(P_PID, pid, result, WEXITED | WNOWAIT) < 0:
                got_errno = waitid_ffi.errno
                if got_errno == errno.EINTR:
                    continue
                raise OSError(got_errno, os.strerror(got_errno))


# adapted from
# https://github.com/python-trio/trio/issues/4#issuecomment-398967572

waitid_limiter = CapacityLimiter(math.inf)

# RunVar mapping pid => Event to set when it completes
waitid_thread_results = _core.RunVar("waitid_thread_results")

async def _waitid_system_task(pid: int) -> None:
    """Spawn a thread that waits for ``pid`` to exit, then wake any tasks
    that were waiting on it.
    """
    # cancellable=True: if this task is cancelled, then we abandon the
    # thread to keep running waitpid in the background. Since this is
    # always run as a system task, this will only happen if the whole
    # call to trio.run is shutting down, in which case the waitid_threads
    # dictionary is too -- so, nothing to clean up.

    try:
        await run_sync_in_worker_thread(
            sync_wait_reapable,
            pid,
            cancellable=True,
            limiter=waitid_limiter
        )
    except Exception:
        # If waitid fails, waitpid will fail too, so it still makes
        # sense to wake up the callers of wait_process_exiting(). The
        # most likely reason for this error in practice is a child
        # exiting when wait() is not possible because SIGCHLD is
        # ignored.
        pass
    finally:
        waitid_thread_results.get().pop(pid).set()


async def wait_child_exiting(pid: int) -> None:
    try:
        return await waitid_thread_results.get()[pid].wait()
    except LookupError:
        waitid_thread_results.set({})
    except KeyError:
        pass
    finished = Event()
    waitid_thread_results.get()[pid] = finished
    _core.spawn_system_task(_waitid_system_task, pid)
    await finished.wait()
