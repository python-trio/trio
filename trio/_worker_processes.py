import os
from itertools import count
from multiprocessing import Pipe, Lock, Process

import outcome

import trio

# How long a process will idle waiting for new work before gives up and exits.
# This should be longer than a thread timeout proportionately to startup time.
IDLE_TIMEOUT = 60 * 10
PROC_COUNTER = count()
IDLE_PROC_CACHE = {}
DEFAULT_PROC_LIMITER = trio.CapacityLimiter(os.cpu_count())

if os.name == "nt":
    # TODO: This uses a thread per-process. Can we do better?
    wait_sentinel = trio.lowlevel.WaitForSingleObject
elif os.name == "posix":
    wait_sentinel = trio.lowlevel.wait_readable
else:
    raise RuntimeError(f"Unsupported OS: {os.name}")


def _prune_expired_procs():
    for proc in list(IDLE_PROC_CACHE):
        if not proc.is_alive():
            del IDLE_PROC_CACHE[proc]


class BrokenWorkerError(Exception):
    pass


class WorkerProc:
    def __init__(self):
        # As with the thread cache, releasing this lock serves to kick a
        # worker process off it's idle countdown and onto the work pipe.
        self._worker_lock = Lock()
        self._worker_lock.acquire()
        self._recv_pipe, self._send_pipe = Pipe()
        self._proc = Process(
            target=self._work,
            args=(self._worker_lock, self._recv_pipe, self._send_pipe),
            name=f"WorkerProc-{next(PROC_COUNTER)}",
            daemon=True,
        )
        self._proc.start()

    @staticmethod
    def _work(lock, recv_pipe, send_pipe):
        while lock.acquire(timeout=IDLE_TIMEOUT):
            # We got a job
            fn, args = recv_pipe.recv()
            result = outcome.capture(fn, *args)
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

    async def run_sync(self, sync_fn, *args):
        async with trio.open_nursery() as nursery:
            await nursery.start(self._child_monitor)
            self._worker_lock.release()
            try:
                await trio.to_thread.run_sync(self._send_pipe.send, (sync_fn, args))
                result = await trio.to_thread.run_sync(self._recv_pipe.recv)
            except trio.Cancelled:
                # Cancellation leaves the process in an unknown state so
                # there is no choice but to kill
                self._proc.kill()
                self._proc.join()
                raise
            # must cancel the child monitor task to exit nursery
            nursery.cancel_scope.cancel()
        return result.unwrap()

    async def _child_monitor(self, task_status):
        task_status.started()
        # If this handle becomes ready, raise a catchable error
        await wait_sentinel(self._proc.sentinel)
        raise BrokenWorkerError(f"{self._proc} died unexpectedly")

    def is_alive(self):
        return self._proc.is_alive()


async def to_process_run_sync(
    sync_fn, *args, cancellable=False, limiter=DEFAULT_PROC_LIMITER
):
    """Run sync_fn in a separate process

    This is a wrapping of multiprocessing.Process that follows the API of
    trio.to_thread.run_sync. The intended use of this function is limited:

    - Circumvent the GIL for CPU-bound functions
    - Make blocking APIs or infinite loops truly cancellable through
      SIGKILL/TerminateProcess without leaking resources
    - Protect main process from untrusted/crashy code without leaks

    Anything else that works is gravy, normal multiprocessing caveats apply."""

    async with limiter:
        _prune_expired_procs()
        try:
            while True:
                proc, _ = IDLE_PROC_CACHE.popitem()
                # Under normal circumstances workers are waiting on lock.acquire
                # for a new job, but if they time out, they die immediately.
                if proc.is_alive():
                    break
        except IndexError:
            proc = await trio.to_thread.run_sync(WorkerProc)

        try:
            with trio.CancelScope(shield=not cancellable):
                return await proc.run_sync(sync_fn, *args)
        finally:
            if proc.is_alive():
                IDLE_PROC_CACHE[proc] = None
