import threading
import queue as stdlib_queue
import time

import pytest

from .. import _core
from ..testing import busy_wait_for, wait_run_loop_idle
from .._threads import *

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
                record.append(("error", type(exc)))
        child_thread = threading.Thread(target=threadfn, daemon=True)
        child_thread.start()
        while child_thread.is_alive():
            print("yawn")
            time.sleep(0.01)
            await _core.yield_briefly()
        assert record == [
            ("start", child_thread), ("f", trio_thread), expected]

    run_in_trio_thread = current_run_in_trio_thread()

    def f(record):
        record.append(("f", threading.current_thread()))
        return 2
    await check_case(run_in_trio_thread, f, ("got", 2))

    def f(record):
        record.append(("f", threading.current_thread()))
        raise ValueError
    await check_case(run_in_trio_thread, f, ("error", ValueError))

    await_in_trio_thread = current_await_in_trio_thread()

    async def f(record):
        await _core.yield_briefly()
        record.append(("f", threading.current_thread()))
        return 3
    await check_case(await_in_trio_thread, f, ("got", 3))

    async def f(record):
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
    task1 = await _core.spawn(child, q, True)
    # Give it a chance to get started...
    await wait_run_loop_idle()
    # ...and then cancel it.
    task1.cancel()
    # The task finishes.
    result = await task1.join()
    assert isinstance(result.error, _core.Cancelled)
    assert register[0] != "finished"
    # But the thread is still there. Put it out of its misery:
    q.put(None)
    while register[0] != "finished":
        time.sleep(0.01)

    # This one can't be cancelled
    register[0] = None
    task2 = await _core.spawn(child, q, False)
    await wait_run_loop_idle()
    task2.cancel()
    for _ in range(10):
        await _core.yield_briefly()
    with pytest.raises(_core.WouldBlock):
        task2.join_nowait()
    q.put(None)
    (await task2.join()).unwrap()

    # But if we cancel *before* it enters, the entry is itself a cancellation
    # point
    task3 = await _core.spawn(child, q, False)
    task3.cancel()
    result = await task3.join()
    assert isinstance(result.error, _core.Cancelled)


def test_run_in_worker_thread_abandoned(capfd):
    q1 = stdlib_queue.Queue()
    q2 = stdlib_queue.Queue()

    def thread_fn():
        q1.get()
        q2.put(threading.current_thread())

    async def main():
        async def child():
            await run_in_worker_thread(thread_fn, cancellable=True)
        t = await _core.spawn(child)
        await wait_run_loop_idle()
        t.cancel()
        (await t.join()).unwrap()

    with pytest.raises(_core.Cancelled):
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
