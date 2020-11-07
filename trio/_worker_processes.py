import os
from collections import deque
from itertools import count
from multiprocessing import Pipe, Process, Barrier
from threading import BrokenBarrierError

import trio
from trio._core import RunVar

_limiter_local = RunVar("proc_limiter")

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


class ProcCache:
    def __init__(self):
        # The cache is a deque rather than dict here since processes can't remove
        # themselves anyways, so we don't need O(1) lookups
        self._cache = deque()

    def prune_expired_procs(self):
        # take advantage of the oldest proc being on the left to
        # keep iteration O(dead)
        while self._cache:
            proc = self._cache.popleft()
            if proc.is_alive():
                self._cache.appendleft(proc)
                break

    def push(self, proc):
        self._cache.append(proc)

    def pop(self):
        """Get live, WOKEN worker process or raise IndexError"""
        while True:
            proc = self._cache.pop()
            try:
                proc.wake_up()
            except BrokenWorkerError:
                continue
            else:
                return proc

    def __len__(self):
        return len(self._cache)


IDLE_PROC_CACHE = ProcCache()


class BrokenWorkerError(RuntimeError):
    pass


class WorkerProc:
    def __init__(self):
        # More heavyweight synchronization is required for processes vs threads
        # because of the lack of shared state. Since only the parent and child
        # processes will ever touch this, simply having them both wait together
        # is enough sign of life to move things onto the pipe.
        self._barrier = Barrier(2)
        # On NT, a single duplexed pipe raises a TrioInternalError: GH#1767
        child_recv_pipe, self._send_pipe = Pipe(duplex=False)
        self._recv_pipe, child_send_pipe = Pipe(duplex=False)
        self._proc = Process(
            target=self._work,
            args=(self._barrier, child_recv_pipe, child_send_pipe),
            name=f"Trio worker process {next(_proc_counter)}",
            daemon=True,
        )
        # The following two initiation methods may take a long time, recommend
        # using a thread to run this
        self._proc.start()
        # proc may need a moment to wake up
        self.wake_up(timeout=1)

    @staticmethod
    def _work(barrier, recv_pipe, send_pipe):

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

        while True:
            try:
                # Return value is party #, not whether awoken within timeout
                barrier.wait(timeout=IDLE_TIMEOUT)
            except BrokenBarrierError:
                # Timeout waiting for job, so we can exit.
                break
            # We got a job, and we are "woken"
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
        # At this point the barrier is "broken" and can be used as a death sign.

    async def run_sync(self, sync_fn, *args):
        # Neither this nor the child process should be waiting at this point
        assert not self._barrier.n_waiting, "Must first wake_up() the WorkerProc"
        async with trio.open_nursery() as nursery:
            try:
                await nursery.start(self._child_monitor)
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
        # dying, but the the barrier should be broken at that time
        return self._proc.is_alive() and not self._barrier.broken

    def wake_up(self, timeout=0):
        # raise an exception if the barrier is broken or we must wait
        try:
            self._barrier.wait(timeout)
        except BrokenBarrierError:
            # raise our own flavor of exception and ensure death
            self.kill()
            raise BrokenWorkerError(f"{self._proc} died unexpectedly") from None

    def kill(self):
        try:
            self._proc.kill()
        except AttributeError:
            self._proc.terminate()


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
        IDLE_PROC_CACHE.prune_expired_procs()

        try:
            proc = IDLE_PROC_CACHE.pop()
        except IndexError:
            proc = await trio.to_thread.run_sync(WorkerProc)

        try:
            with trio.CancelScope(shield=not cancellable):
                return await proc.run_sync(sync_fn, *args)
        finally:
            if proc.is_alive():
                IDLE_PROC_CACHE.push(proc)
