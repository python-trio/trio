import os
from collections import deque
from itertools import count
from multiprocessing import Pipe, Lock, Process

import trio
from trio._core import RunVar

_limiter_local = RunVar("proc_limiter")

# The cache is a deque rather than dict here since processes can't remove
# themselves anyways, so we don't need O(1) lookups
IDLE_PROC_CACHE = deque()
# How long a process will idle waiting for new work before gives up and exits.
# This should be longer than a thread timeout proportionately to startup time.
IDLE_TIMEOUT = 60 * 10

# Sane default might be to expect cpu-bound work
DEFAULT_LIMIT = os.cpu_count()
_proc_counter = count()


def current_default_process_limiter():
    """Get the default `~trio.CapacityLimiter` used by
    `trio.to_process.run_sync`.

    The most common reason to call this would be if you want to modify its
    :attr:`~trio.CapacityLimiter.total_tokens` attribute.

    """
    try:
        limiter = _limiter_local.get()
    except LookupError:
        limiter = trio.CapacityLimiter(DEFAULT_LIMIT)
        _limiter_local.set(limiter)
    return limiter


if os.name == "nt":
    # TODO: This uses a thread per-process. Can we do better?
    wait_sentinel = trio.lowlevel.WaitForSingleObject
else:
    wait_sentinel = trio.lowlevel.wait_readable


def _prune_expired_procs():
    # take advantage of the oldest proc being on the left to
    # keep iteration O(dead)
    while IDLE_PROC_CACHE:
        proc = IDLE_PROC_CACHE.popleft()
        if proc.is_alive():
            IDLE_PROC_CACHE.appendleft(proc)
            break


class BrokenWorkerError(Exception):
    pass


class WorkerProc:
    def __init__(self):
        # As with the thread cache, releasing this lock serves to kick a
        # worker process off it's idle countdown and onto the work pipe.
        self._worker_lock = Lock()
        self._worker_lock.acquire()
        # On NT, a single duplexed pipe raises a TrioInternalError: GH#1767
        child_recv_pipe, self._send_pipe = Pipe(duplex=False)
        self._recv_pipe, child_send_pipe = Pipe(duplex=False)
        self._proc = Process(
            target=self._work,
            args=(self._worker_lock, child_recv_pipe, child_send_pipe),
            name=f"Trio worker process {next(_proc_counter)}",
            daemon=True,
        )
        self._proc.start()

    @staticmethod
    def _work(lock, recv_pipe, send_pipe):

        import inspect
        import outcome

        def worker_fn():
            ret = fn(*args)
            if inspect.iscoroutine(ret):
                # Manually close coroutine to avoid RuntimeWarnings
                ret.close()
                raise TypeError(
                    "Trio expected a sync function, but {!r} appears to be "
                    "asynchronous".format(getattr(fn, "__qualname__", fn))
                )

            return ret

        while lock.acquire(timeout=IDLE_TIMEOUT):
            # We got a job
            fn, args = recv_pipe.recv()
            result = outcome.capture(worker_fn)
            # Tell the cache that we're done and available for a job
            # Unlike the thread cache, it's impossible to deliver the
            # result from the worker process. So shove it onto the queue
            # and hope the receiver delivers the result and marks us idle
            send_pipe.send(result)

            del fn
            del args
            del result
        # Timeout acquiring lock, so we can probably exit.
        # Unlike thread cache, the race condition of someone trying to
        # assign a job as we quit must be checked by the assigning task.
        # This lock can provide a signal that is available before the sentinel.
        lock.release()

    async def run_sync(self, sync_fn, *args):
        async with trio.open_nursery() as nursery:
            await nursery.start(self._child_monitor)
            self._worker_lock.release()
            try:
                await trio.to_thread.run_sync(
                    self._send_pipe.send, (sync_fn, args), cancellable=True
                )
                result = await trio.to_thread.run_sync(
                    self._recv_pipe.recv, cancellable=True
                )
            except trio.Cancelled:
                # Cancellation leaves the process in an unknown state so
                # there is no choice but to kill, anyway it frees the pipe threads
                self.kill()
                raise
            except EOFError:
                # Likely the worker died while we were waiting on a pipe
                self.kill()
                # sleep and let the monitor raise the appropriate error
                await trio.sleep_forever()
            # must cancel the child monitor task to exit nursery
            nursery.cancel_scope.cancel()
        return result.unwrap()

    async def _child_monitor(self, task_status):
        task_status.started()
        # If this handle becomes ready, raise a catchable error
        await wait_sentinel(self._proc.sentinel)
        raise BrokenWorkerError(f"{self._proc} died unexpectedly")

    def is_alive(self):
        # if the proc is alive, there is a race condition where it could be
        # dying, but the lock should be released during most of this condition
        if self._proc.is_alive():
            if self._worker_lock.acquire(block=False):
                # if we acquire, we should release it again ASAP in case
                # someone else checks later
                self._worker_lock.release()
                return False
            return True
        return False

    def kill(self):
        try:
            self._proc.kill()
        except AttributeError:
            self._proc.terminate()
        self._proc.join()


async def to_process_run_sync(sync_fn, *args, cancellable=False, limiter=None):
    """Run sync_fn in a separate process

    This is a wrapping of multiprocessing.Process that follows the API of
    trio.to_thread.run_sync. The intended use of this function is limited:

    - Circumvent the GIL for CPU-bound functions
    - Make blocking APIs or infinite loops truly cancellable through
      SIGKILL/TerminateProcess without leaking resources
    - Protect main process from untrusted/crashy code without leaks

    Anything else that works is gravy, normal multiprocessing caveats apply."""
    if limiter is None:
        limiter = current_default_process_limiter()

    async with limiter:
        _prune_expired_procs()
        try:
            # Get the most-recently-idle worker process
            # Race condition: worker process might have timed out between
            # prune and pop so loop until we get a live one or IndexError
            while True:
                proc = IDLE_PROC_CACHE.pop()
                if proc.is_alive():
                    break
        except IndexError:
            proc = await trio.to_thread.run_sync(WorkerProc)

        try:
            with trio.CancelScope(shield=not cancellable):
                return await proc.run_sync(sync_fn, *args)
        finally:
            if proc.is_alive():
                IDLE_PROC_CACHE.append(proc)
