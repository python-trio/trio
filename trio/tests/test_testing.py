import pytest

from .. import sleep
from .. import _core
from ..testing import *

async def test_wait_run_loop_idle():
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

async def test_wait_run_loop_idle_with_timeouts(mock_clock):
    record = []
    async def timeout_task():
        record.append("tt start")
        await sleep(5)
        record.append("tt finished")
    async with _core.open_nursery() as nursery:
        t = nursery.spawn(timeout_task)
        await wait_all_tasks_blocked()
        assert record == ["tt start"]
        mock_clock.advance(10)
        await wait_all_tasks_blocked()
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
