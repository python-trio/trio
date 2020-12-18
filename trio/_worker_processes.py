import os
from collections import deque
from itertools import count
from multiprocessing import Pipe, Process

from ._core import open_nursery, RunVar, CancelScope, wait_readable
from ._sync import CapacityLimiter
from ._threads import to_thread_run_sync
from ._timeouts import sleep_forever

_limiter_local = RunVar("proc_limiter")

# How long a process will idle waiting for new work before gives up and exits.
# This should be longer than a thread timeout proportionately to startup time.
IDLE_TIMEOUT = 60 * 10

# Sane default might be to expect cpu-bound work
DEFAULT_LIMIT = os.cpu_count()
_proc_counter = count()

if os.name == "nt":
    from ._wait_for_object import WaitForSingleObject

    # TODO: This uses a thread per-process. Can we do better?
    wait_sentinel = WaitForSingleObject
else:
    wait_sentinel = wait_readable


class BrokenWorkerError(RuntimeError):
    """Raised when a worker process fails or dies unexpectedly.

    This error is not typically encountered in normal use, and indicates a severe
    failure of either Trio or the code that was executing in the worker.
    """

    pass


def current_default_process_limiter():
    """Get the default `~trio.CapacityLimiter` used by
    `trio.to_process.run_sync`.

    The most common reason to call this would be if you want to modify its
    :attr:`~trio.CapacityLimiter.total_tokens` attribute. This attribute
    is initialized to the number of CPUs reported by :func:`os.cpu_count`.

    """
    try:
        limiter = _limiter_local.get()
    except LookupError:
        limiter = CapacityLimiter(DEFAULT_LIMIT)
        _limiter_local.set(limiter)
    return limiter


class ProcCache:
    def __init__(self):
        # The cache is a deque rather than dict here since processes can't remove
        # themselves anyways, so we don't need O(1) lookups
        self._cache = deque()
        # NOTE: avoid thread races between Trio runs by only interacting with
        # self._cache via thread-atomic actions like append, pop, del

    def prune(self):
        # take advantage of the oldest proc being on the left to
        # keep iteration O(dead workers)
        try:
            while True:
                proc = self._cache.popleft()
                if proc.is_alive():
                    self._cache.appendleft(proc)
                    return
        except IndexError:
            # Thread safety: it's necessary to end the iteration using this error
            # when the cache is empty, as opposed to `while self._cache`.
            pass

    def push(self, proc):
        self._cache.append(proc)

    def pop(self):
        """Get live worker process or raise IndexError"""
        while True:
            proc = self._cache.pop()
            if proc.is_alive():
                return proc

    def __len__(self):
        return len(self._cache)


PROC_CACHE = ProcCache()


class WorkerProc:
    def __init__(self):
        child_recv_pipe, self._send_pipe = Pipe(duplex=False)
        self._recv_pipe, child_send_pipe = Pipe(duplex=False)
        self._proc = Process(
            target=self._work,
            args=(child_recv_pipe, child_send_pipe),
            name=f"Trio worker process {next(_proc_counter)}",
            daemon=True,
        )
        # The following initialization methods may take a long time
        self._proc.start()

    @staticmethod
    def _work(recv_pipe, send_pipe):  # pragma: no cover

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

        try:
            while recv_pipe.poll(timeout=IDLE_TIMEOUT):
                fn, args = recv_pipe.recv()
                result = outcome.capture(worker_fn)
                # Unlike the thread cache, it's impossible to deliver the
                # result from the worker process. So shove it onto the queue
                # and hope the receiver delivers the result and marks us idle
                send_pipe.send(result)

                del fn
                del args
                del result
        finally:
            recv_pipe.close()
            send_pipe.close()

    async def run_sync(self, sync_fn, *args):
        # Neither this nor the child process should be waiting at this point
        async with open_nursery() as nursery:
            try:
                # Monitor needed for pypy and other platforms that don't
                # promptly raise EOFError
                await nursery.start(self._child_monitor)

                await to_thread_run_sync(
                    self._send_pipe.send, (sync_fn, args), cancellable=True
                )
                result = await to_thread_run_sync(
                    self._recv_pipe.recv, cancellable=True
                )
            except EOFError:
                # Likely the worker died while we were waiting on a pipe
                self.kill()  # Just make sure
                # sleep and let the monitor raise the appropriate error to avoid
                # creating any MultiErrors in this codepath
                await sleep_forever()
            except BaseException:
                # Cancellation leaves the process in an unknown state, so
                # there is no choice but to kill, anyway it frees the pipe threads.
                # For other unknown errors, it's best to clean up similarly.
                self.kill()
                raise
            # Must cancel the _child_monitor task to escape the nursery
            nursery.cancel_scope.cancel()
        return result.unwrap()

    async def _child_monitor(self, task_status):
        task_status.started()
        # quickly raise if the pipes have been closed
        self._recv_pipe.poll(timeout=0)
        # If this handle becomes ready, raise a catchable error
        await wait_sentinel(self._proc.sentinel)
        raise BrokenWorkerError(f"{self._proc} died unexpectedly")

    def is_alive(self):
        # Even if the proc is alive, there is a race condition where it could
        # be dying, use join to make sure if necessary.
        return self._proc.is_alive()

    def kill(self):
        try:
            self._proc.kill()
        except AttributeError:
            self._proc.terminate()

    def join(self, timeout=None):
        # Needed for some tests. We have to reach in deeply because
        # _proc.join() doesn't report whether the join was successful
        return self._proc._popen.wait(timeout) is not None


async def to_process_run_sync(sync_fn, *args, cancellable=False, limiter=None):
    """Run sync_fn in a separate process

    This is a wrapping of :class:`multiprocessing.Process` that follows the API of
    :func:`trio.to_thread.run_sync`. The intended use of this function is limited:

    - Circumvent the GIL to run CPU-bound functions in parallel
    - Make blocking APIs or infinite loops truly cancellable through
      SIGKILL/TerminateProcess without leaking resources
    - Protect the main process from untrusted/unstable code without leaks

    Other :mod:`multiprocessing` features may work but are not officially
    supported by Trio, and all the normal :mod:`multiprocessing` caveats apply.

    Args:
      sync_fn: An importable or pickleable synchronous callable. See the
          :mod:`multiprocessing` documentation for detailed explanation of
          limitations.
      *args: Positional arguments to pass to sync_fn. If you need keyword
          arguments, use :func:`functools.partial`.
      cancellable (bool): Whether to allow cancellation of this operation.
          Cancellation always involves abrupt termination of the worker process
          with SIGKILL/TerminateProcess.
      limiter (None, or CapacityLimiter):
          An object used to limit the number of simultaneous processes. Most
          commonly this will be a `~trio.CapacityLimiter`, but any async
          context manager will succeed.

    Returns:
      Whatever ``sync_fn(*args)`` returns.

    Raises:
      Exception: Whatever ``sync_fn(*args)`` raises.

    """
    if limiter is None:
        limiter = current_default_process_limiter()

    async with limiter:
        PROC_CACHE.prune()

        while True:
            try:
                proc = PROC_CACHE.pop()
            except IndexError:
                proc = await to_thread_run_sync(WorkerProc)

            try:
                with CancelScope(shield=not cancellable):
                    return await proc.run_sync(sync_fn, *args)
            except BrokenPipeError:
                # Rare case where proc timed out even though it was still alive
                # as we popped it. Just retry.
                pass
            finally:
                if proc.is_alive():
                    PROC_CACHE.push(proc)
