import threading
import queue as stdlib_queue
import time

import pytest

from .. import _core
from ..testing import busy_wait_for
from .._threads import *

async def test_run_in_trio_thread():
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


@pytest.mark.foo
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
