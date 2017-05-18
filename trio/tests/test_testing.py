import time
from math import inf

import pytest

from .. import sleep
from .. import _core
from .. import _streams
from ..testing import *
from ..testing import _assert_raises, _UnboundedByteQueue

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


async def test_wait_all_tasks_blocked_with_tiebreaker():
    record = []

    async def do_wait(cushion, tiebreaker):
        await wait_all_tasks_blocked(cushion=cushion, tiebreaker=tiebreaker)
        record.append((cushion, tiebreaker))

    async with _core.open_nursery() as nursery:
        nursery.spawn(do_wait, 0, 0)
        nursery.spawn(do_wait, 0, -1)
        nursery.spawn(do_wait, 0, 1)
        nursery.spawn(do_wait, 0, -1)
        nursery.spawn(do_wait, 0.0001, 10)
        nursery.spawn(do_wait, 0.0001, -10)

    assert record == sorted(record)
    assert record == [
        (0, -1),
        (0, -1),
        (0, 0),
        (0, 1),
        (0.0001, -10),
        (0.0001, 10),
    ]


################################################################

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

    # But both together count as a checkpoint
    with assert_yields():
        await _core.yield_if_cancelled()
        await _core.yield_briefly()
    with pytest.raises(AssertionError):
        with assert_no_yields():
            await _core.yield_if_cancelled()
            await _core.yield_briefly()


################################################################

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


################################################################

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
    await wait_all_tasks_blocked(cushion=0.02, tiebreaker=float("inf"))
    # And again with threshold=0, because that has some special
    # busy-wait-avoidance logic:
    mock_clock.autojump_threshold = 0
    await wait_all_tasks_blocked(tiebreaker=float("inf"))

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


async def test_mock_clock_autojump_0_and_wait_all_tasks_blocked(mock_clock):
    # Checks that autojump_threshold=0 doesn't interfere with
    # calling wait_all_tasks_blocked with the default cushion=0 and arbitrary
    # tiebreakers.

    mock_clock.autojump_threshold = 0

    record = []

    async def sleeper():
        await sleep(100)
        record.append("yawn")

    async def waiter():
        for i in range(10):
            await wait_all_tasks_blocked(tiebreaker=i)
            record.append(i)
        await sleep(1000)
        record.append("waiter done")

    async with _core.open_nursery() as nursery:
        nursery.spawn(sleeper)
        nursery.spawn(waiter)

    assert record == list(range(10)) + ["yawn", "waiter done"]


################################################################

async def test__assert_raises():
    with pytest.raises(AssertionError):
        with _assert_raises(RuntimeError):
            1 + 1

    with pytest.raises(TypeError):
        with _assert_raises(RuntimeError):
            "foo" + 1

    with _assert_raises(RuntimeError):
        raise RuntimeError

# This is a private implementation detail, but it's complex enough to be worth
# testing directly
async def test__UnboundeByteQueue():
    ubq = _UnboundedByteQueue()

    ubq.put(b"123")
    ubq.put(b"456")
    assert ubq.get_nowait(1) == b"1"
    assert ubq.get_nowait(10) == b"23456"
    ubq.put(b"789")
    assert ubq.get_nowait() == b"789"

    with pytest.raises(_core.WouldBlock):
        ubq.get_nowait(10)
    with pytest.raises(_core.WouldBlock):
        ubq.get_nowait()

    with pytest.raises(TypeError):
        ubq.put("string")

    ubq.put(b"abc")
    with assert_yields():
        assert await ubq.get(10) == b"abc"
    ubq.put(b"def")
    ubq.put(b"ghi")
    with assert_yields():
        assert await ubq.get(1) == b"d"
    with assert_yields():
        assert await ubq.get() == b"efghi"

    async def putter(data):
        await wait_all_tasks_blocked()
        ubq.put(data)

    async def getter(expect):
        with assert_yields():
            assert await ubq.get() == expect

    async with _core.open_nursery() as nursery:
        nursery.spawn(getter, b"xyz")
        nursery.spawn(putter, b"xyz")

    # Two gets at the same time -> ResourceBusyError
    with pytest.raises(_core.ResourceBusyError):
        async with _core.open_nursery() as nursery:
            nursery.spawn(getter, b"asdf")
            nursery.spawn(getter, b"asdf")

    # Closing

    ubq.close()
    with pytest.raises(_streams.ClosedStreamError):
        ubq.put(b"---")

    assert ubq.get_nowait(10) == b""
    assert ubq.get_nowait() == b""
    assert await ubq.get(10) == b""
    assert await ubq.get() == b""

    # close is idempotent
    ubq.close()

    # close wakes up blocked getters
    ubq2 = _UnboundedByteQueue()

    async def closer():
        await wait_all_tasks_blocked()
        ubq2.close()

    async with _core.open_nursery() as nursery:
        nursery.spawn(getter, b"")
        nursery.spawn(closer)


async def test_MemorySendStream():
    mss = MemorySendStream()

    async def do_send_all(data):
        with assert_yields():
            await mss.send_all(data)

    await do_send_all(b"123")
    assert mss.get_data_nowait(1) == b"1"
    assert mss.get_data_nowait() == b"23"

    with assert_yields():
        await mss.wait_send_all_might_not_block()

    with pytest.raises(_core.WouldBlock):
        mss.get_data_nowait()
    with pytest.raises(_core.WouldBlock):
        mss.get_data_nowait(10)

    await do_send_all(b"456")
    with assert_yields():
        assert await mss.get_data() == b"456"

    with pytest.raises(_core.ResourceBusyError):
        async with _core.open_nursery() as nursery:
            nursery.spawn(do_send_all, b"xxx")
            nursery.spawn(do_send_all, b"xxx")

    with assert_yields():
        await mss.graceful_close()

    assert await mss.get_data() == b"xxx"
    assert await mss.get_data() == b""
    with pytest.raises(_streams.ClosedStreamError):
        await do_send_all(b"---")

    # hooks

    assert mss.send_all_hook is None
    assert mss.wait_send_all_might_not_block_hook is None
    assert mss.close_hook is None

    record = []
    async def send_all_hook():
        # hook runs after send_all does its work (can pull data out)
        assert mss2.get_data_nowait() == b"abc"
        record.append("send_all_hook")
    async def wait_send_all_might_not_block_hook():
        record.append("wait_send_all_might_not_block_hook")
    def close_hook():
        record.append("close_hook")

    mss2 = MemorySendStream(
        send_all_hook,
        wait_send_all_might_not_block_hook,
        close_hook,
    )

    assert mss2.send_all_hook is send_all_hook
    assert mss2.wait_send_all_might_not_block_hook is wait_send_all_might_not_block_hook
    assert mss2.close_hook is close_hook

    await mss2.send_all(b"abc")
    await mss2.wait_send_all_might_not_block()
    mss2.forceful_close()

    assert record == [
        "send_all_hook",
        "wait_send_all_might_not_block_hook",
        "close_hook",
    ]


async def test_MemoryRecieveStream():
    mrs = MemoryReceiveStream()

    async def do_receive_some(max_bytes):
        with assert_yields():
            return await mrs.receive_some(max_bytes)

    mrs.put_data(b"abc")
    assert await do_receive_some(1) == b"a"
    assert await do_receive_some(10) == b"bc"
    with pytest.raises(TypeError):
        await do_receive_some(None)

    with pytest.raises(_core.ResourceBusyError):
        async with _core.open_nursery() as nursery:
            nursery.spawn(do_receive_some, 10)
            nursery.spawn(do_receive_some, 10)

    assert mrs.receive_some_hook is None

    mrs.put_data(b"def")
    mrs.put_eof()
    mrs.put_eof()

    assert await do_receive_some(10) == b"def"
    assert await do_receive_some(10) == b""
    assert await do_receive_some(10) == b""

    with pytest.raises(_streams.ClosedStreamError):
        mrs.put_data(b"---")

    record = []
    async def receive_some_hook():
        mrs2.put_data(b"xxx")

    mrs2 = MemoryReceiveStream(receive_some_hook)
    assert mrs2.receive_some_hook is receive_some_hook

    mrs2.put_data(b"yyy")
    assert await mrs2.receive_some(10) == b"yyyxxx"
    assert await mrs2.receive_some(10) == b"xxx"
    assert await mrs2.receive_some(10) == b"xxx"

    mrs2.put_data(b"zzz")
    mrs2.receive_some_hook = None
    assert await mrs2.receive_some(10) == b"zzz"

    mrs2.put_data(b"lost on close")
    with assert_yields():
        await mrs2.graceful_close()

    with pytest.raises(_streams.ClosedStreamError):
        await mrs2.receive_some(10)


async def test_MemoryRecvStream_closing():
    mrs = MemoryReceiveStream()
    # close with no pending data
    mrs.forceful_close()
    with pytest.raises(_streams.ClosedStreamError):
        assert await mrs.receive_some(10) == b""
    # repeated closes ok
    mrs.forceful_close()
    # put_data now fails
    with pytest.raises(_streams.ClosedStreamError):
        mrs.put_data(b"123")

    mrs2 = MemoryReceiveStream()
    # close with pending data
    mrs2.put_data(b"xyz")
    mrs2.forceful_close()
    with pytest.raises(_streams.ClosedStreamError):
        await mrs2.receive_some(10)


async def test_memory_stream_pump():
    mss = MemorySendStream()
    mrs = MemoryReceiveStream()

    # no-op if no data present
    memory_stream_pump(mss, mrs)

    await mss.send_all(b"123")
    memory_stream_pump(mss, mrs)
    assert await mrs.receive_some(10) == b"123"

    await mss.send_all(b"456")
    assert memory_stream_pump(mss, mrs, max_bytes=1)
    assert await mrs.receive_some(10) == b"4"
    assert memory_stream_pump(mss, mrs, max_bytes=1)
    assert memory_stream_pump(mss, mrs, max_bytes=1)
    assert not memory_stream_pump(mss, mrs, max_bytes=1)
    assert await mrs.receive_some(10) == b"56"

    mss.forceful_close()
    memory_stream_pump(mss, mrs)
    assert await mrs.receive_some(10) == b""


async def test_memory_stream_one_way_pair():
    s, r = memory_stream_one_way_pair()
    assert s.send_all_hook is not None
    assert s.wait_send_all_might_not_block_hook is None
    assert s.close_hook is not None
    assert r.receive_some_hook is None
    await s.send_all(b"123")
    assert await r.receive_some(10) == b"123"

    # This fails if we pump on r.receive_some_hook; we need to pump on s.send_all_hook
    async def sender():
        await wait_all_tasks_blocked()
        await s.send_all(b"abc")

    async def receiver(expected):
        assert await r.receive_some(10) == expected

    async with _core.open_nursery() as nursery:
        nursery.spawn(receiver, b"abc")
        nursery.spawn(sender)

    # And this fails if we don't pump from close_hook
    async def graceful_closer():
        await wait_all_tasks_blocked()
        await s.graceful_close()

    async with _core.open_nursery() as nursery:
        nursery.spawn(receiver, b"")
        nursery.spawn(graceful_closer)

    s, r = memory_stream_one_way_pair()

    async def forceful_closer():
        await wait_all_tasks_blocked()
        s.forceful_close()

    async with _core.open_nursery() as nursery:
        nursery.spawn(receiver, b"")
        nursery.spawn(forceful_closer)

    s, r = memory_stream_one_way_pair()

    old = s.send_all_hook
    s.send_all_hook = None
    await s.send_all(b"456")

    async def cancel_after_idle(nursery):
        await wait_all_tasks_blocked()
        nursery.cancel_scope.cancel()

    async def check_for_cancel():
        with pytest.raises(_core.Cancelled):
            # This should block forever... or until cancelled. Even though we
            # sent some data on the send stream.
            await r.receive_some(10)

    async with _core.open_nursery() as nursery:
        nursery.spawn(cancel_after_idle, nursery)
        nursery.spawn(check_for_cancel)

    s.send_all_hook = old
    await s.send_all(b"789")
    assert await r.receive_some(10) == b"456789"


async def test_memory_stream_pair():
    a, b = memory_stream_pair()
    await a.send_all(b"123")
    await b.send_all(b"abc")
    assert await b.receive_some(10) == b"123"
    assert await a.receive_some(10) == b"abc"

    await a.send_eof()
    assert await b.receive_some(10) == b""

    async def sender():
        await wait_all_tasks_blocked()
        await b.send_all(b"xyz")

    async def receiver():
        assert await a.receive_some(10) == b"xyz"

    async with _core.open_nursery() as nursery:
        nursery.spawn(receiver)
        nursery.spawn(sender)


async def test_memory_streams_with_generic_tests():
    async def one_way_stream_maker():
        return memory_stream_one_way_pair()
    await check_one_way_stream(one_way_stream_maker, None)

    async def half_closeable_stream_maker():
        return memory_stream_pair()
    await check_half_closeable_stream(half_closeable_stream_maker, None)


async def test_lockstep_streams_with_generic_tests():
    async def one_way_stream_maker():
        return lockstep_stream_one_way_pair()
    await check_one_way_stream(one_way_stream_maker, one_way_stream_maker)

    async def two_way_stream_maker():
        return lockstep_stream_pair()
    await check_two_way_stream(two_way_stream_maker, two_way_stream_maker)
