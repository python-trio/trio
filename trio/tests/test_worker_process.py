import multiprocessing
import os

import pytest

from .. import _core, fail_after
from .. import _worker_processes
from .._core.tests.tutil import slow
from .._worker_processes import to_process_run_sync, current_default_process_limiter
from ..testing import wait_all_tasks_blocked
from .._threads import to_thread_run_sync


@pytest.fixture(autouse=True)
def empty_proc_cache():
    while True:
        try:
            proc = _worker_processes.IDLE_PROC_CACHE.pop()
            proc.kill()
        except IndexError:
            return


def _echo_and_pid(x):  # pragma: no cover
    return (x, os.getpid())


def _raise_pid():  # pragma: no cover
    raise ValueError(os.getpid())


@slow
async def test_run_in_worker_process():
    trio_pid = os.getpid()

    x, child_pid = await to_process_run_sync(_echo_and_pid, 1)
    assert x == 1
    assert child_pid != trio_pid

    with pytest.raises(ValueError) as excinfo:
        await to_process_run_sync(_raise_pid)
    print(excinfo.value.args)
    assert excinfo.value.args[0] != trio_pid


def _block_proc_on_queue(q, ev, done_ev):  # pragma: no cover
    # Make the thread block for a controlled amount of time
    ev.set()
    q.get()
    done_ev.set()


@slow
async def test_run_in_worker_process_cancellation(capfd):
    async def child(q, ev, done_ev, cancellable):
        print("start")
        try:
            return await to_process_run_sync(
                _block_proc_on_queue, q, ev, done_ev, cancellable=cancellable
            )
        finally:
            print("exit")

    m = multiprocessing.Manager()
    q = m.Queue()
    ev = m.Event()
    done_ev = m.Event()

    # This one can't be cancelled
    async with _core.open_nursery() as nursery:
        nursery.start_soon(child, q, ev, done_ev, False)
        await to_thread_run_sync(ev.wait, cancellable=True)
        nursery.cancel_scope.cancel()
        with _core.CancelScope(shield=True):
            await wait_all_tasks_blocked(0.01)
        # It's still running
        assert not done_ev.is_set()
        q.put(None)
        # Now it exits

    ev = m.Event()
    done_ev = m.Event()
    # But if we cancel *before* it enters, the entry is itself a cancellation
    # point
    with _core.CancelScope() as scope:
        scope.cancel()
        await child(q, ev, done_ev, False)
    assert scope.cancelled_caught
    capfd.readouterr()

    ev = m.Event()
    done_ev = m.Event()
    # This is truly cancellable by killing the process
    async with _core.open_nursery() as nursery:
        nursery.start_soon(child, q, ev, done_ev, True)
        # Give it a chance to get started. (This is important because
        # to_thread_run_sync does a checkpoint_if_cancelled before
        # blocking on the thread, and we don't want to trigger this.)
        await wait_all_tasks_blocked()
        assert capfd.readouterr().out.rstrip() == "start"
        await to_thread_run_sync(ev.wait, cancellable=True)
        # Then cancel it.
        nursery.cancel_scope.cancel()
    # The task exited, but the process died
    assert not done_ev.is_set()
    assert capfd.readouterr().out.rstrip() == "exit"


def _null_func():  # pragma: no cover
    pass


async def test_run_in_worker_process_fail_to_spawn(monkeypatch):
    # Test the unlikely but possible case where trying to spawn a worker fails
    def bad_start():
        raise RuntimeError("the engines canna take it captain")

    monkeypatch.setattr(_worker_processes, "WorkerProc", bad_start)

    limiter = current_default_process_limiter()
    assert limiter.borrowed_tokens == 0

    # We get an appropriate error, and the limiter is cleanly released
    with pytest.raises(RuntimeError) as excinfo:
        await to_process_run_sync(_null_func)  # pragma: no cover
    assert "engines" in str(excinfo.value)

    assert limiter.borrowed_tokens == 0


async def _null_async_fn():  # pragma: no cover
    pass


@slow
async def test_trio_to_process_run_sync_expected_error():
    with pytest.raises(TypeError, match="expected a sync function"):
        await to_process_run_sync(_null_async_fn)


def _segfault_out_of_bounds_pointer():  # pragma: no cover
    # https://wiki.python.org/moin/CrashingPython
    import ctypes

    i = ctypes.c_char(b"a")
    j = ctypes.pointer(i)
    c = 0
    while True:
        j[c] = b"a"
        c += 1


@slow
async def test_to_process_run_sync_raises_on_segfault():
    with pytest.raises(_worker_processes.BrokenWorkerError):
        await to_process_run_sync(_segfault_out_of_bounds_pointer)


def _never_halts(ev):  # pragma: no cover
    # important difference from blocking call is cpu usage
    ev.set()
    while True:
        pass


@slow
async def test_to_process_run_sync_cancel_infinite_loop():
    m = multiprocessing.Manager()
    ev = m.Event()

    async def child():
        await to_process_run_sync(_never_halts, ev, cancellable=True)

    async with _core.open_nursery() as nursery:
        nursery.start_soon(child)
        await to_thread_run_sync(ev.wait, cancellable=True)
        nursery.cancel_scope.cancel()


def _proc_queue_pid_fn(ev, q):  # pragma: no cover
    ev.set()
    q.put(None)
    return os.getpid()


@slow
async def test_to_process_run_sync_cancel_blocking_call():
    m = multiprocessing.Manager()
    ev = m.Event()
    q = m.Queue()
    pid = None

    async def child():
        await to_thread_run_sync(ev.wait, cancellable=True)
        nursery.cancel_scope.cancel()

    async with _core.open_nursery() as nursery:
        nursery.start_soon(child)
        pid = await to_process_run_sync(_proc_queue_pid_fn, ev, q, cancellable=True)
    # This makes sure:
    # - the process actually ran
    # - that process has finished before we check for its output

    assert nursery.cancel_scope.cancelled_caught
    assert pid is None

    # TODO: Shouldn't this raise empty?
    # from queue import Empty
    # with pytest.raises(Empty):
    #     q.get_nowait()


@slow
async def test_spawn_worker_in_thread_and_prune_cache():
    # make sure we can successfully put worker spawning in a trio thread
    proc = await to_thread_run_sync(_worker_processes.WorkerProc)
    # take it's number and kill it for the next test
    pid1 = proc._proc.pid
    proc.kill()
    proc._proc.join()
    # put dead proc into the cache (normal code never does this)
    _worker_processes.IDLE_PROC_CACHE.push(proc)
    # should spawn a new worker and remove the dead one
    _, pid2 = await to_process_run_sync(_echo_and_pid, None)
    assert len(_worker_processes.IDLE_PROC_CACHE) == 1
    assert pid1 != pid2


@slow
async def test_to_process_run_sync_large_job():
    n = 2 ** 20
    x, _ = await to_process_run_sync(_echo_and_pid, bytearray(n))
    assert len(x) == n
