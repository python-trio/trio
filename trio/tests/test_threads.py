import threading
import queue as stdlib_queue
import time
import os
import signal

import pytest

from .. import _core
from .. import Event
from ..testing import wait_all_tasks_blocked
from .._threads import *
from .._timeouts import sleep

from .._core.tests.test_ki import ki_self

async def test_do_in_trio_thread():
    trio_thread = threading.current_thread()

    async def check_case(do_in_trio_thread, fn, expected):
        record = []
        def threadfn():
            try:
                record.append(("start", threading.current_thread()))
                x = do_in_trio_thread(fn, record)
                record.append(("got", x))
            except BaseException as exc:
                print(exc)
                record.append(("error", type(exc)))
        child_thread = threading.Thread(target=threadfn, daemon=True)
        child_thread.start()
        while child_thread.is_alive():
            print("yawn")
            await sleep(0.01)
        assert record == [
            ("start", child_thread), ("f", trio_thread), expected]

    run_in_trio_thread = current_run_in_trio_thread()

    def f(record):
        assert not _core.currently_ki_protected()
        record.append(("f", threading.current_thread()))
        return 2
    await check_case(run_in_trio_thread, f, ("got", 2))

    def f(record):
        assert not _core.currently_ki_protected()
        record.append(("f", threading.current_thread()))
        raise ValueError
    await check_case(run_in_trio_thread, f, ("error", ValueError))

    await_in_trio_thread = current_await_in_trio_thread()

    async def f(record):
        assert not _core.currently_ki_protected()
        await _core.yield_briefly()
        record.append(("f", threading.current_thread()))
        return 3
    await check_case(await_in_trio_thread, f, ("got", 3))

    async def f(record):
        assert not _core.currently_ki_protected()
        await _core.yield_briefly()
        record.append(("f", threading.current_thread()))
        raise KeyError
    await check_case(await_in_trio_thread, f, ("error", KeyError))


async def test_do_in_trio_thread_from_trio_thread():
    run_in_trio_thread = current_run_in_trio_thread()
    await_in_trio_thread = current_await_in_trio_thread()

    with pytest.raises(RuntimeError):
        run_in_trio_thread(lambda: None)  # pragma: no branch

    async def foo():  # pragma: no cover
        pass
    with pytest.raises(RuntimeError):
        await_in_trio_thread(foo)


def test_run_in_trio_thread_ki():
    # if we get a control-C during a run_in_trio_thread, then it propagates
    # back to the caller (slick!)
    record = set()
    async def check_run_in_trio_thread():
        run_in_trio_thread = current_run_in_trio_thread()
        await_in_trio_thread = current_await_in_trio_thread()
        def trio_thread_fn():
            print("in trio thread")
            assert not _core.currently_ki_protected()
            print("ki_self")
            try:
                ki_self()
            finally:
                import sys
                print("finally", sys.exc_info())
        async def trio_thread_afn():
            trio_thread_fn()
        def external_thread_fn():
            try:
                print("running")
                run_in_trio_thread(trio_thread_fn)
            except KeyboardInterrupt:
                print("ok1")
                record.add("ok1")
            try:
                await_in_trio_thread(trio_thread_afn)
            except KeyboardInterrupt:
                print("ok2")
                record.add("ok2")
        thread = threading.Thread(target=external_thread_fn)
        thread.start()
        print("waiting")
        while thread.is_alive():
            await sleep(0.01)
        print("waited, joining")
        thread.join()
        print("done")
    _core.run(check_run_in_trio_thread)
    assert record == {"ok1", "ok2"}


def test_await_in_trio_thread_while_main_exits():
    record = []
    ev = Event()

    async def trio_fn():
        record.append("sleeping")
        ev.set()
        await _core.yield_indefinitely(lambda _: _core.Abort.SUCCEEDED)

    def thread_fn(await_in_trio_thread):
        try:
            await_in_trio_thread(trio_fn)
        except _core.Cancelled:
            record.append("cancelled")

    async def main():
        aitt = current_await_in_trio_thread()
        thread = threading.Thread(target=thread_fn, args=(aitt,))
        thread.start()
        await ev.wait()
        assert record == ["sleeping"]
        return thread

    thread = _core.run(main)
    thread.join()
    assert record == ["sleeping", "cancelled"]


async def test_run_in_worker_thread():
    trio_thread = threading.current_thread()

    def f(x):
        return (x, threading.current_thread())
    x, child_thread = await run_in_worker_thread(f, 1)
    assert x == 1
    assert child_thread != trio_thread

    def g():
        raise ValueError(threading.current_thread())
    with pytest.raises(ValueError) as excinfo:
        await run_in_worker_thread(g)
    print(excinfo.value.args)
    assert excinfo.value.args[0] != trio_thread


async def test_run_in_worker_thread_cancellation():
    register = [None]
    def f(q):
        # Make the thread block for a controlled amount of time
        register[0] = "blocking"
        q.get()
        register[0] = "finished"

    async def child(q, cancellable):
        return await run_in_worker_thread(f, q, cancellable=cancellable)

    q = stdlib_queue.Queue()
    async with _core.open_nursery() as nursery:
        task1 = nursery.spawn(child, q, True)
        # Give it a chance to get started. (This is important because
        # run_in_worker_thread does a yield_if_cancelled before blocking on
        # the thread, and we don't want to trigger this.)
        await wait_all_tasks_blocked()
        # Then cancel it.
        nursery.cancel_scope.cancel()
    # The task exited, but the thread didn't:
    assert register[0] != "finished"
    # Put the thread out of its misery:
    q.put(None)
    while register[0] != "finished":
        time.sleep(0.01)

    # This one can't be cancelled
    register[0] = None
    async with _core.open_nursery() as nursery:
        task2 = nursery.spawn(child, q, False)
        await wait_all_tasks_blocked()
        nursery.cancel_scope.cancel()
        with _core.open_cancel_scope(shield=True):
            for _ in range(10):
                await _core.yield_briefly()
        # It's still running
        assert task2.result is None
        q.put(None)
        # Now it exits

    # But if we cancel *before* it enters, the entry is itself a cancellation
    # point
    with _core.open_cancel_scope() as scope:
        scope.cancel()
        await child(q, False)
    assert scope.cancelled_caught


# Make sure that if trio.run exits, and then the thread finishes, then that's
# handled gracefully. (Requires that the thread result machinery be prepared
# for call_soon to raise RunFinishedError.)
def test_run_in_worker_thread_abandoned(capfd):
    q1 = stdlib_queue.Queue()
    q2 = stdlib_queue.Queue()

    def thread_fn():
        q1.get()
        q2.put(threading.current_thread())

    async def main():
        async def child():
            await run_in_worker_thread(thread_fn, cancellable=True)
        async with _core.open_nursery() as nursery:
            t = nursery.spawn(child)
            await wait_all_tasks_blocked()
            nursery.cancel_scope.cancel()
    _core.run(main)

    q1.put(None)
    # This makes sure:
    # - the thread actually ran
    # - that thread has finished before we check for its output
    thread = q2.get()
    while thread.is_alive():
        time.sleep(0.01)  # pragma: no cover

    # Make sure we don't have a "Exception in thread ..." dump to the console:
    out, err = capfd.readouterr()
    assert not out and not err


