import contextlib
import threading
import time
from math import inf

import pytest

from trio import Event, move_on_after, sleep, sleep_forever

from ... import _abc, _core
from .. import wait_all_tasks_blocked
from .._mock_clock import MockClock
from .._run import GLOBAL_RUN_CONTEXT
from .tutil import slow


def test_mock_clock() -> None:
    REAL_NOW = 123.0
    c = MockClock()
    c._real_clock = lambda: REAL_NOW
    repr(c)  # smoke test
    assert c.rate == 0
    assert c.current_time() == 0
    c.jump(1.2)
    assert c.current_time() == 1.2
    with pytest.raises(ValueError, match=r"^time can't go backwards$"):
        c.jump(-1)
    assert c.current_time() == 1.2
    assert c.deadline_to_sleep_time(1.1) == 0
    assert c.deadline_to_sleep_time(1.2) == 0
    assert c.deadline_to_sleep_time(1.3) > 999999

    with pytest.raises(ValueError, match=r"^rate must be >= 0$"):
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


async def test_mock_clock_autojump(mock_clock: MockClock) -> None:
    assert mock_clock.autojump_threshold == inf

    mock_clock.autojump_threshold = 0
    assert mock_clock.autojump_threshold == 0

    real_start = time.perf_counter()

    virtual_start = _core.current_time()
    for i in range(10):
        print(f"sleeping {10 * i} seconds")
        await sleep(10 * i)
        print("woke up!")
        assert virtual_start + 10 * i == _core.current_time()
        virtual_start = _core.current_time()

    real_duration = time.perf_counter() - real_start
    print(f"Slept {10 * sum(range(10))} seconds in {real_duration} seconds")
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

    # set up a situation where the autojump task is blocked for a long long
    # time, to make sure that cancel-and-adjust-threshold logic is working
    mock_clock.autojump_threshold = 10000
    await wait_all_tasks_blocked()
    mock_clock.autojump_threshold = 0
    # if the above line didn't take affect immediately, then this would be
    # bad:
    # ignore ASYNC116, not sleep_forever, trying to test a large but finite sleep
    await sleep(100000)  # noqa: ASYNC116


async def test_mock_clock_autojump_interference(mock_clock: MockClock) -> None:
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
    # ignore ASYNC116, not sleep_forever, trying to test a large but finite sleep
    await sleep(100000)  # noqa: ASYNC116


def test_mock_clock_autojump_preset() -> None:
    # Check that we can set the autojump_threshold before the clock is
    # actually in use, and it gets picked up
    mock_clock = MockClock(autojump_threshold=0.1)
    mock_clock.autojump_threshold = 0.01
    real_start = time.perf_counter()
    _core.run(sleep, 10000, clock=mock_clock)
    assert time.perf_counter() - real_start < 1


async def test_mock_clock_autojump_0_and_wait_all_tasks_blocked_0(
    mock_clock: MockClock,
) -> None:
    # Checks that autojump_threshold=0 doesn't interfere with
    # calling wait_all_tasks_blocked with the default cushion=0.

    mock_clock.autojump_threshold = 0

    record = []

    async def sleeper() -> None:
        await sleep(100)
        record.append("yawn")

    async def waiter() -> None:
        await wait_all_tasks_blocked()
        record.append("waiter woke")
        await sleep(1000)
        record.append("waiter done")

    async with _core.open_nursery() as nursery:
        nursery.start_soon(sleeper)
        nursery.start_soon(waiter)

    assert record == ["waiter woke", "yawn", "waiter done"]


@slow
async def test_mock_clock_autojump_0_and_wait_all_tasks_blocked_nonzero(
    mock_clock: MockClock,
) -> None:
    # Checks that autojump_threshold=0 doesn't interfere with
    # calling wait_all_tasks_blocked with a non-zero cushion.

    mock_clock.autojump_threshold = 0

    record = []

    async def sleeper() -> None:
        await sleep(100)
        record.append("yawn")

    async def waiter() -> None:
        await wait_all_tasks_blocked(1)
        record.append("waiter done")

    async with _core.open_nursery() as nursery:
        nursery.start_soon(sleeper)
        nursery.start_soon(waiter)

    assert record == ["waiter done", "yawn"]


async def test_initialization_doesnt_mutate_runner() -> None:
    before = (
        GLOBAL_RUN_CONTEXT.runner.clock,
        GLOBAL_RUN_CONTEXT.runner.clock_autojump_threshold,
    )

    MockClock(autojump_threshold=2, rate=3)

    after = (
        GLOBAL_RUN_CONTEXT.runner.clock,
        GLOBAL_RUN_CONTEXT.runner.clock_autojump_threshold,
    )
    assert before == after


@pytest.mark.parametrize("hold", [False, True])
async def test_hold_autojump_while_waiting_for_thread(
    autojump_clock: MockClock,
    hold: bool,
) -> None:
    # A task parked in wait_task_rescheduled until a non-Trio thread wakes it
    # through run_sync_soon looks idle to the run loop. Without a hold the
    # clock jumps while the thread is still working; with one, virtual time
    # waits for the thread. The thread works until ``proceed`` is set: by the
    # sleeper (so only once the clock has jumped) or, when the clock is held
    # and cannot jump, as soon as every task is blocked.
    record = []
    proceed = threading.Event()

    async def wait_for_thread() -> None:
        task = _core.current_task()
        token = _core.current_trio_token()

        def thread_fn() -> None:
            proceed.wait()
            # Not needed by a correct clock; it gives a broken one time to jump.
            time.sleep(0.05)
            token.run_sync_soon(_core.reschedule, task)

        thread = threading.Thread(target=thread_fn)
        thread.start()
        try:
            with _core.hold_autojump() if hold else contextlib.nullcontext():
                await _core.wait_task_rescheduled(lambda _: _core.Abort.FAILED)
        finally:
            proceed.set()
            thread.join()
        record.append(("thread", _core.current_time()))

    async def sleeper() -> None:
        await sleep(10)
        record.append(("sleeper", _core.current_time()))
        proceed.set()

    async def release_thread_if_held() -> None:
        await wait_all_tasks_blocked()
        if hold:
            proceed.set()

    async with _core.open_nursery() as nursery:
        nursery.start_soon(wait_for_thread)
        nursery.start_soon(sleeper)
        nursery.start_soon(release_thread_if_held)

    if hold:
        assert record == [("thread", 0), ("sleeper", 10)]
    else:
        assert record == [("sleeper", 10), ("thread", 10)]


async def test_hold_autojump_across_run_sync_soon_callbacks(
    autojump_clock: MockClock,
) -> None:
    # run_sync_soon callbacks run inside a task, so one callback can enter the
    # block and a later one, here sent from another thread, can exit it.
    token = _core.current_trio_token()
    hold = _core.hold_autojump()
    done = Event()

    def finished() -> None:
        hold.__exit__(None, None, None)
        done.set()

    def thread_fn() -> None:
        time.sleep(0.2)
        token.run_sync_soon(finished)

    # Queued before this task blocks, so it runs before the loop can go idle.
    token.run_sync_soon(hold.__enter__)
    thread = threading.Thread(target=thread_fn)
    thread.start()
    try:
        with move_on_after(60) as scope:
            await done.wait()
    finally:
        thread.join()
    assert not scope.cancelled_caught
    assert _core.current_time() == 0
    assert GLOBAL_RUN_CONTEXT.runner.autojump_holds == 0


async def test_hold_autojump_nests_and_always_releases(
    autojump_clock: MockClock,
) -> None:
    runner = GLOBAL_RUN_CONTEXT.runner
    with _core.hold_autojump():
        with _core.hold_autojump():
            assert runner.autojump_holds == 2
        assert runner.autojump_holds == 1
    assert runner.autojump_holds == 0

    with pytest.raises(KeyError):
        with _core.hold_autojump():
            raise KeyError
    assert runner.autojump_holds == 0

    with _core.CancelScope() as scope:
        with _core.hold_autojump():
            scope.cancel()
            await sleep_forever()
    assert scope.cancelled_caught
    assert runner.autojump_holds == 0

    # ...and the clock autojumps again afterwards
    start = _core.current_time()
    await sleep(3)
    assert _core.current_time() - start == 3


def test_hold_autojump_with_real_clock() -> None:
    # Under a real clock there is no autojump to hold; the block is harmless.
    async def main() -> None:
        with _core.hold_autojump():
            await sleep(0.01)

    _core.run(main)


def test_hold_autojump_outside_task() -> None:
    with pytest.raises(RuntimeError, match=r"^must be called from async context$"):
        with _core.hold_autojump():
            pass  # pragma: no cover

    # Inside a run but between task steps is refused too: that is what keeps
    # the count from changing between the run loop arming the autojump and
    # firing it. (Exceptions in instrument hooks are swallowed, hence record.)
    record = []

    class TryToHold(_abc.Instrument):
        def before_io_wait(self, timeout: float) -> None:
            try:
                with _core.hold_autojump():
                    record.append("allowed")  # pragma: no cover
            except RuntimeError:
                record.append("refused")

    _core.run(_core.checkpoint, instruments=[TryToHold()])
    assert record
    assert set(record) == {"refused"}


async def test_hold_autojump_exit_inside_another_run(
    autojump_clock: MockClock,
) -> None:
    # A hold belongs to the run it was entered in. Exiting the block from
    # inside a different run is a misuse, which fails an assertion; but it
    # still releases the original run's unit and leaves the other run's count
    # alone.
    runner = GLOBAL_RUN_CONTEXT.runner
    hold = _core.hold_autojump()
    hold.__enter__()
    other_run_count = []

    async def exit_here() -> None:
        with pytest.raises(AssertionError, match="outside the run"):
            hold.__exit__(None, None, None)
        other_run_count.append(GLOBAL_RUN_CONTEXT.runner.autojump_holds)

    thread = threading.Thread(target=_core.run, args=(exit_here,))
    thread.start()
    thread.join()
    assert other_run_count == [0]
    assert runner.autojump_holds == 0
