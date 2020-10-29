import multiprocessing
import os
import time

import pytest

from .. import _core
from .. import Event, CapacityLimiter, sleep
from .. import _worker_processes
from .._worker_processes import (
    to_process_run_sync,
    current_default_process_limiter,
)
from ..testing import wait_all_tasks_blocked
from .._threads import to_thread_run_sync


def _echo_and_pid(x):
    return (x, os.getpid())


def _raise_pid():
    raise ValueError(os.getpid())


async def test_run_in_worker_process():
    trio_pid = os.getpid()

    x, child_pid = await to_process_run_sync(_echo_and_pid, 1)
    assert x == 1
    assert child_pid != trio_pid

    with pytest.raises(ValueError) as excinfo:
        await to_process_run_sync(_raise_pid)
    print(excinfo.value.args)
    assert excinfo.value.args[0] != trio_pid


def _block_proc_on_queue(q, ev):
    # Make the thread block for a controlled amount of time
    ev.set()
    q.get()


async def test_run_in_worker_process_cancellation(capfd):
    async def child(q, ev, cancellable):
        print("start")
        try:
            return await to_process_run_sync(
                _block_proc_on_queue, q, ev, cancellable=cancellable
            )
        finally:
            print("exit")
    m = multiprocessing.Manager()
    q = m.Queue()
    ev = m.Event()

    # This one can't be cancelled
    async with _core.open_nursery() as nursery:
        nursery.start_soon(child, q, ev, False)
        await to_thread_run_sync(ev.wait)
        nursery.cancel_scope.cancel()
        # It's still running
        assert "finished" not in capfd.readouterr().out
        q.put(None)
        # Now it exits

    ev = m.Event()
    # But if we cancel *before* it enters, the entry is itself a cancellation
    # point
    with _core.CancelScope() as scope:
        scope.cancel()
        await child(q, ev, False)
    assert scope.cancelled_caught
    capfd.readouterr()

    ev = m.Event()
    # This is truly cancellable by killing the process
    async with _core.open_nursery() as nursery:
        nursery.start_soon(child, q, ev, True)
        # Give it a chance to get started. (This is important because
        # to_thread_run_sync does a checkpoint_if_cancelled before
        # blocking on the thread, and we don't want to trigger this.)
        await wait_all_tasks_blocked()
        assert capfd.readouterr().out.rstrip() == "start"
        await to_thread_run_sync(ev.wait)
        # Then cancel it.
        nursery.cancel_scope.cancel()
    # The task exited, but the process died
    # TODO: test death
    assert capfd.readouterr().out.rstrip() == "exit"


# TODO?
# @pytest.mark.parametrize("MAX", [3, 5, 10])
# @pytest.mark.parametrize("cancel", [False, True])
# @pytest.mark.parametrize("use_default_limiter", [False, True])
# async def test_run_in_worker_thread_limiter(MAX, cancel, use_default_limiter):
#     # This test is a bit tricky. The goal is to make sure that if we set
#     # limiter=CapacityLimiter(MAX), then in fact only MAX threads are ever
#     # running at a time, even if there are more concurrent calls to
#     # to_thread_run_sync, and even if some of those are cancelled. And
#     # also to make sure that the default limiter actually limits.
#     COUNT = 2 * MAX
#     gate = threading.Event()
#     lock = threading.Lock()
#     if use_default_limiter:
#         c = current_default_process_limiter()
#         orig_total_tokens = c.total_tokens
#         c.total_tokens = MAX
#         limiter_arg = None
#     else:
#         c = CapacityLimiter(MAX)
#         orig_total_tokens = MAX
#         limiter_arg = c
#     try:
#         # We used to use regular variables and 'nonlocal' here, but it turns
#         # out that it's not safe to assign to closed-over variables that are
#         # visible in multiple threads, at least as of CPython 3.6 and PyPy
#         # 5.8:
#         #
#         #   https://bugs.python.org/issue30744
#         #   https://bitbucket.org/pypy/pypy/issues/2591/
#         #
#         # Mutating them in-place is OK though (as long as you use proper
#         # locking etc.).
#         class state:
#             pass
#
#         state.ran = 0
#         state.high_water = 0
#         state.running = 0
#         state.parked = 0
#
#         token = _core.current_trio_token()
#
#         def thread_fn(cancel_scope):
#             print("thread_fn start")
#             from_thread_run_sync(cancel_scope.cancel, trio_token=token)
#             with lock:
#                 state.ran += 1
#                 state.running += 1
#                 state.high_water = max(state.high_water, state.running)
#                 # The Trio thread below watches this value and uses it as a
#                 # signal that all the stats calculations have finished.
#                 state.parked += 1
#             gate.wait()
#             with lock:
#                 state.parked -= 1
#                 state.running -= 1
#             print("thread_fn exiting")
#
#         async def run_thread(event):
#             with _core.CancelScope() as cancel_scope:
#                 await to_thread_run_sync(
#                     thread_fn, cancel_scope, limiter=limiter_arg, cancellable=cancel
#                 )
#             print("run_thread finished, cancelled:", cancel_scope.cancelled_caught)
#             event.set()
#
#         async with _core.open_nursery() as nursery:
#             print("spawning")
#             events = []
#             for i in range(COUNT):
#                 events.append(Event())
#                 nursery.start_soon(run_thread, events[-1])
#                 await wait_all_tasks_blocked()
#             # In the cancel case, we in particular want to make sure that the
#             # cancelled tasks don't release the semaphore. So let's wait until
#             # at least one of them has exited, and that everything has had a
#             # chance to settle down from this, before we check that everyone
#             # who's supposed to be waiting is waiting:
#             if cancel:
#                 print("waiting for first cancellation to clear")
#                 await events[0].wait()
#                 await wait_all_tasks_blocked()
#             # Then wait until the first MAX threads are parked in gate.wait(),
#             # and the next MAX threads are parked on the semaphore, to make
#             # sure no-one is sneaking past, and to make sure the high_water
#             # check below won't fail due to scheduling issues. (It could still
#             # fail if too many threads are let through here.)
#             while state.parked != MAX or c.statistics().tasks_waiting != MAX:
#                 await sleep(0.01)  # pragma: no cover
#             # Then release the threads
#             gate.set()
#
#         assert state.high_water == MAX
#
#         if cancel:
#             # Some threads might still be running; need to wait to them to
#             # finish before checking that all threads ran. We can do this
#             # using the CapacityLimiter.
#             while c.borrowed_tokens > 0:
#                 await sleep(0.01)  # pragma: no cover
#
#         assert state.ran == COUNT
#         assert state.running == 0
#     finally:
#         c.total_tokens = orig_total_tokens


def _null_func():
    pass


async def test_run_in_worker_process_fail_to_spawn(monkeypatch):
    # Test the unlikely but possible case where trying to spawn a thread fails
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


async def test_trio_to_process_run_sync_expected_error():
    # Test correct error when passed async function
    async def async_fn():  # pragma: no cover
        pass

    with pytest.raises(TypeError, match="expected a sync function"):
        await to_process_run_sync(_null_async_fn)


def _segfault():
    # https://wiki.python.org/moin/CrashingPython you beautiful nerds
    import ctypes

    i = ctypes.c_char(b"a")
    j = ctypes.pointer(i)
    c = 0
    while True:
        j[c] = b"a"
        c += 1


async def test_to_process_run_sync_raises_on_segfault():
    # TODO: what error do we want to see here?
    with pytest.raises(EOFError):
        await to_process_run_sync(_segfault)


def _never_halts(ev):
    ev.set()
    while True:
        time.sleep(1)


async def test_to_process_run_sync_cancel_infinite_loop():
    m=multiprocessing.Manager()
    ev = m.Event()

    async def child():
        await to_process_run_sync(_never_halts, ev, cancellable=True)

    async with _core.open_nursery() as nursery:
        nursery.start_soon(child)
        await to_thread_run_sync(ev.wait)
        nursery.cancel_scope.cancel()


def _proc_queue_pid_fn(ev, q1, q2):
    ev.set()
    q1.get()
    q2.put(os.getpid())


async def test_to_process_run_sync_cancel_blocking_call():
    m = multiprocessing.Manager()
    ev = m.Event()
    q1 = m.Queue()
    q2 = m.Queue()

    async def child():
        await to_process_run_sync(_proc_queue_pid_fn, ev, q1, q2, cancellable=True)

    async with _core.open_nursery() as nursery:
        nursery.start_soon(child)
        await to_thread_run_sync(ev.wait)
        q1.put(None)
        nursery.cancel_scope.cancel()

    # This makes sure:
    # - the process actually ran
    # - that process has finished before we check for its output

    # TODO: Shouldn't this fail?
    pid = q2.get()


async def test_spawn_worker_in_thread():
    proc = await to_thread_run_sync(_worker_processes.WorkerProc)
    proc._proc.kill()
    proc._proc.join()


def _echo(x):
    return x


async def test_to_process_run_sync_large_job():
    n = 2 ** 20
    x = await to_process_run_sync(_echo, bytearray(n))
    assert len(x) == n

# TODO: Can't monkeypatch worker processes!
# async def test_idle_proc_cache_prunes_dead_workers(monkeypatch):
#     monkeypatch.setattr(_worker_processes, "IDLE_TIMEOUT", 0.01)
#     async with _core.open_nursery() as nursery:
#         for _ in range(4):
#             nursery.start_soon(to_process_run_sync, int)
#     time.sleep(.02)  # very sorry
#     await to_process_run_sync(int)
#     assert len(_worker_processes.IDLE_PROC_CACHE) == 1
