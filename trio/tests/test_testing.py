import time
from math import inf

import pytest

from .. import sleep
from .. import _core
from ..testing import *

async def test_wait_all_tasks_blocked():
    record = []
    async def busy_bee():
        for _ in range(10):
            await _core.yield_briefly()
        record.append("busy bee exhausted")

    async def waiting_for_bee_to_leave():
        await wait_all_tasks_blocked()
        record.append("quiet at last!")

    async with _core.open_nursery() as nursery:
        t1 = nursery.spawn(busy_bee)
        t2 = nursery.spawn(waiting_for_bee_to_leave)
        t3 = nursery.spawn(waiting_for_bee_to_leave)

    # check cancellation
    async def cancelled_while_waiting():
        try:
            await wait_all_tasks_blocked()
        except _core.Cancelled:
            return "ok"
    async with _core.open_nursery() as nursery:
        t4 = nursery.spawn(cancelled_while_waiting)
        nursery.cancel_scope.cancel()
    assert t4.result.unwrap() == "ok"

async def test_wait_all_tasks_blocked_with_timeouts(mock_clock):
    record = []
    async def timeout_task():
        record.append("tt start")
        await sleep(5)
        record.append("tt finished")
    async with _core.open_nursery() as nursery:
        t = nursery.spawn(timeout_task)
        await wait_all_tasks_blocked()
        assert record == ["tt start"]
        mock_clock.jump(10)
        await wait_all_tasks_blocked()
        assert record == ["tt start", "tt finished"]


async def test_wait_all_tasks_blocked_with_cushion():
    record = []
    async def blink():
        record.append("blink start")
        await sleep(0.01)
        await sleep(0.01)
        await sleep(0.01)
        record.append("blink end")

    async def wait_no_cushion():
        await wait_all_tasks_blocked()
        record.append("wait_no_cushion end")

    async def wait_small_cushion():
        await wait_all_tasks_blocked(0.02)
        record.append("wait_small_cushion end")

    async def wait_big_cushion():
        await wait_all_tasks_blocked(0.03)
        record.append("wait_big_cushion end")

    async with _core.open_nursery() as nursery:
        nursery.spawn(blink)
        nursery.spawn(wait_no_cushion)
        nursery.spawn(wait_small_cushion)
        nursery.spawn(wait_small_cushion)
        nursery.spawn(wait_big_cushion)
    assert record == [
        "blink start",
        "wait_no_cushion end",
        "blink end",
        "wait_small_cushion end",
        "wait_small_cushion end",
        "wait_big_cushion end",
    ]

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

    # partial yield cases
    # if you have a schedule point but not a cancel point, or vice-versa, then
    # that doesn't make *either* version of assert_{no_,}yields happy.
    for partial_yield in [
            _core.yield_if_cancelled, _core.yield_briefly_no_cancel]:
        for block in [assert_yields, assert_no_yields]:
            print(partial_yield, block)
            with pytest.raises(AssertionError):
                with block():
                    await partial_yield()

    # But both together count as a yield point
    with assert_yields():
        await _core.yield_if_cancelled()
        await _core.yield_briefly()
    with pytest.raises(AssertionError):
        with assert_no_yields():
            await _core.yield_if_cancelled()
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
    async with _core.open_nursery() as nursery:
        t1 = nursery.spawn(f1, seq)
        t2 = nursery.spawn(f2, seq)
        async with seq(5):
            await t1.wait()
            await t2.wait()
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
        with _core.open_cancel_scope() as scope:
            if i == 1:
                scope.cancel()
            try:
                async with seq(i):
                    pass  # pragma: no cover
            except RuntimeError:
                record.append("seq({}) RuntimeError".format(i))

    async with _core.open_nursery() as nursery:
        t1 = nursery.spawn(child, 1)
        t2 = nursery.spawn(child, 2)
        async with seq(0):
            pass  # pragma: no cover

    assert record == ["seq(1) RuntimeError", "seq(2) RuntimeError"]

    # Late arrivals also get errors
    with pytest.raises(RuntimeError):
        async with seq(3):
            pass  # pragma: no cover


def test_mock_clock():
    REAL_NOW = 123.0
    c = MockClock()
    c._real_clock = lambda: REAL_NOW
    repr(c)  # smoke test
    assert c.rate == 0
    assert c.current_time() == 0
    c.jump(1.2)
    assert c.current_time() == 1.2
    with pytest.raises(ValueError):
        c.jump(-1)
    assert c.current_time() == 1.2
    assert c.deadline_to_sleep_time(1.1) == 0
    assert c.deadline_to_sleep_time(1.2) == 0
    assert c.deadline_to_sleep_time(1.3) > 999999

    with pytest.raises(ValueError):
        c.rate = -1
    assert c.rate == 0

    c.rate = 2
    assert c.current_time() == 1.2
    REAL_NOW += 1
    assert c.current_time() == 3.2
    assert c.deadline_to_sleep_time(3.1) == 0
    assert c.deadline_to_sleep_time(3.2) == 0
    assert c.deadline_to_sleep_time(4.2) == 0.5

    c.rate = 0.5
    assert c.current_time() == 3.2
    assert c.deadline_to_sleep_time(3.1) == 0
    assert c.deadline_to_sleep_time(3.2) == 0
    assert c.deadline_to_sleep_time(4.2) == 2.0

    c.jump(0.8)
    assert c.current_time() == 4.0
    REAL_NOW += 1
    assert c.current_time() == 4.5


    c2 = MockClock(rate=3)
    assert c2.rate == 3
    assert c2.current_time() < 10


async def test_mock_clock_autojump(mock_clock):
    assert mock_clock.autojump_threshold == inf

    mock_clock.autojump_threshold = 0
    assert mock_clock.autojump_threshold == 0

    real_start = time.monotonic()

    virtual_start = _core.current_time()
    for i in range(10):
        print("sleeping {} seconds".format(10 * i))
        await sleep(10 * i)
        print("woke up!")
        assert virtual_start + 10 * i == _core.current_time()
        virtual_start = _core.current_time()

    real_duration = time.monotonic() - real_start
    print("Slept {} seconds in {} seconds"
          .format(10 * sum(range(10)), real_duration))
    assert real_duration < 1

    mock_clock.autojump_threshold = 0.02
    t = _core.current_time()
    # this should wake up before the autojump threshold triggers, so time
    # shouldn't change
    await wait_all_tasks_blocked()
    assert t == _core.current_time()
    # this should too
    await wait_all_tasks_blocked(0.01)
    assert t == _core.current_time()

    # This should wake up at the same time as the autojump_threshold, and
    # confuse things. There is no deadline, so it shouldn't actually jump
    # the clock. But does it handle the situation gracefully?
    await wait_all_tasks_blocked(0.02)
    # And again with threshold=0, because that has some special
    # busy-wait-avoidance logic:
    mock_clock.autojump_threshold = 0
    await wait_all_tasks_blocked()

    # set up a situation where the autojump task is blocked for a long long
    # time, to make sure that cancel-and-adjust-threshold logic is working
    mock_clock.autojump_threshold = 10000
    await wait_all_tasks_blocked()
    mock_clock.autojump_threshold = 0
    # if the above line didn't take affect immediately, then this would be
    # bad:
    await sleep(100000)


async def test_mock_clock_autojump_interference(mock_clock):
    mock_clock.autojump_threshold = 0.02

    mock_clock2 = MockClock()
    # messing with the autojump threshold of a clock that isn't actually
    # installed in the run loop shouldn't do anything.
    mock_clock2.autojump_threshold = 0.01

    # if the autojump_threshold of 0.01 were in effect, then the next line
    # would block forever, as the autojump task kept waking up to try to
    # jump the clock.
    await wait_all_tasks_blocked(0.015)

    # but the 0.02 limit does apply
    await sleep(100000)


def test_mock_clock_autojump_preset():
    # Check that we can set the autojump_threshold before the clock is
    # actually in use, and it gets picked up
    mock_clock = MockClock(autojump_threshold=0.1)
    mock_clock.autojump_threshold = 0.01
    real_start = time.monotonic()
    _core.run(sleep, 10000, clock=mock_clock)
    assert time.monotonic() - real_start < 1
