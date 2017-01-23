import pytest

from .. import sleep
from .. import _core
from ..testing import *

async def test_busy_wait_for():
    record = []
    register = [0]
    async def child(childname, values):
        for value in values:
            await busy_wait_for(lambda: register[0] == value)
            record.append("{}{}".format(childname, value))
            register[0] += 1

    await _core.spawn(child, "a", [0, 3, 4])
    await _core.spawn(child, "b", [1, 2])
    c = await _core.spawn(child, "c", [5])
    await c.join()

    assert record == ["a0", "b1", "b2", "a3", "a4", "c5"]


async def test_wait_run_loop_idle():
    record = []
    async def busy_bee():
        for _ in range(10):
            await _core.yield_briefly()
        record.append("busy bee exhausted")

    async def waiting_for_bee_to_leave():
        await wait_run_loop_idle()
        record.append("quiet at last!")

    t1 = await _core.spawn(busy_bee)
    t2 = await _core.spawn(waiting_for_bee_to_leave)
    t3 = await _core.spawn(waiting_for_bee_to_leave)
    (await t1.join()).unwrap()
    (await t2.join()).unwrap()
    (await t3.join()).unwrap()

    # check cancellation
    async def cancelled_while_waiting():
        _core.current_task().cancel()
        try:
            await wait_run_loop_idle()
        except _core.Cancelled:
            return "ok"
    t4 = await _core.spawn(cancelled_while_waiting)
    assert (await t4.join()).unwrap() == "ok"

async def test_wait_run_loop_idle_with_timeouts(mock_clock):
    record = []
    async def timeout_task():
        record.append("tt start")
        await sleep(5)
        record.append("tt finished")
    t = await _core.spawn(timeout_task)
    await wait_run_loop_idle()
    assert record == ["tt start"]
    mock_clock.advance(10)
    await wait_run_loop_idle()
    assert record == ["tt start", "tt finished"]


async def test_assert_yields():
    with assert_yields():
        await _core.yield_briefly()

    with pytest.raises(AssertionError):
        with assert_yields():
            1 + 1

    with assert_no_yields():
        1 + 1

    with pytest.raises(AssertionError):
        with assert_no_yields():
            await _core.yield_briefly()


async def test_Sequencer():
    record = []
    def t(val):
        print(val)
        record.append(val)

    async def f1(seq):
        async with seq(1):
            t(("f1", 1))
        async with seq(3):
            t(("f1", 3))
        async with seq(4):
            t(("f1", 4))

    async def f2(seq):
        async with seq(0):
            t(("f2", 0))
        async with seq(2):
            t(("f2", 2))

    seq = Sequencer()
    t1 = await _core.spawn(f1, seq)
    t2 = await _core.spawn(f2, seq)
    async with seq(5):
        await t1.join()
        await t2.join()
        assert record == [("f2", 0), ("f1", 1), ("f2", 2), ("f1", 3), ("f1", 4)]

    seq = Sequencer()
    # Catches us if we try to re-use a sequence point:
    async with seq(0):
        pass
    with pytest.raises(RuntimeError):
        async with seq(0):
            pass  # pragma: no cover


async def test_Sequencer_cancel():
    # Killing a blocked task makes everything blow up
    record = []
    seq = Sequencer()
    async def child(i):
        try:
            async with seq(i):
                pass  # pragma: no cover
        except RuntimeError:
            record.append("seq({}) RuntimeError".format(i))
    t1 = await _core.spawn(child, 1)
    t2 = await _core.spawn(child, 2)
    t1.cancel()
    print(1)
    async with seq(0):
        pass  # pragma: no cover
    print(2)
    (await t1.join()).unwrap()
    print(2)
    (await t2.join()).unwrap()
    print(2)
    assert record == ["seq(1) RuntimeError", "seq(2) RuntimeError"]

    # Late arrivals also get errors
    with pytest.raises(RuntimeError):
        async with seq(3):
            pass  # pragma: no cover
