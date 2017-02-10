import threading
import sys
import time
from math import inf

import pytest
import attr

from .test_util import check_sequence_matches, check_exc_chain
from ...testing import busy_wait_for, wait_run_loop_idle, Sequencer

from ... import _core

async def sleep_forever():
    return await _core.yield_indefinitely(lambda: _core.Abort.SUCCEEDED)

def test_basic():
    async def trivial(x):
        return x
    assert _core.run(trivial, 8) == 8

    with pytest.raises(TypeError):
        # Missing an argument
        _core.run(trivial)

    with pytest.raises(TypeError):
        # Not an async function
        _core.run(lambda: None)

    async def trivial2(x):
        await _core.yield_briefly()
        return x
    assert _core.run(trivial2, 1) == 1


def test_initial_task_error():
    async def main(x):
        raise ValueError(x)

    with pytest.raises(ValueError) as excinfo:
        _core.run(main, 17)
    assert excinfo.value.args == (17,)


def test_run_nesting():
    async def inception():
        async def main():  # pragma: no cover
            pass
        return _core.run(main)
    with pytest.raises(RuntimeError) as excinfo:
        _core.run(inception)
    assert "from inside" in str(excinfo.value)


async def test_basic_spawn_wait():
    async def child(x):
        return 2 * x
    async with _core.open_nursery() as nursery:
        task = nursery.spawn(child, 10)
        await task.wait()
        assert task.result.unwrap() == 20


async def test_child_crash_basic():
    exc = ValueError("uh oh")
    async def erroring():
        raise exc

    async with _core.open_nursery() as nursery:
        task = nursery.spawn(erroring)
        await task.wait()
        assert task.result.error is exc
        nursery.reap(task)

    try:
        # nursery.__aexit__ propagates exception from child back to parent
        async with _core.open_nursery() as nursery:
            nursery.spawn(erroring)
    except ValueError as e:
        assert e is exc


async def test_basic_interleave():
    async def looper(whoami, record):
        for i in range(3):
            record.append((whoami, i))
            await _core.yield_briefly()

    record = []
    async with _core.open_nursery() as nursery:
        t1 = nursery.spawn(looper, "a", record)
        t2 = nursery.spawn(looper, "b", record)

    check_sequence_matches(record, [
        {("a", 0), ("b", 0)},
        {("a", 1), ("b", 1)},
        {("a", 2), ("b", 2)}])


def test_task_crash_propagation():
    looper_record = []
    async def looper():
        try:
            while True:
                print("looper sleeping")
                await _core.yield_briefly()
                print("looper woke up")
        except _core.Cancelled:
            print("looper cancelled")
            looper_record.append("cancelled")

    async def crasher():
        raise ValueError("argh")

    async def main():
        async with _core.open_nursery() as nursery:
            nursery.spawn(looper)
            nursery.spawn(crasher)

    with pytest.raises(ValueError) as excinfo:
        _core.run(main)

    assert looper_record == ["cancelled"]
    assert excinfo.value.args == ("argh",)


def test_main_and_task_both_crash():
    # If main crashes and there's also a task crash, then we get both in a
    # MultiError
    async def crasher():
        raise ValueError

    async def main(wait):
        async with _core.open_nursery() as nursery:
            crasher_task = nursery.spawn(crasher)
            if wait:
                await crasher_task.wait()
            raise KeyError

    for wait in [True, False]:
        with pytest.raises(_core.MultiError) as excinfo:
            _core.run(main, wait)
        print(excinfo.value)
        assert set(type(exc) for exc in excinfo.value.exceptions) == {
            ValueError, KeyError}


def test_two_child_crashes():
    async def crasher(etype):
        raise etype

    async def main():
        async with _core.open_nursery() as nursery:
            nursery.spawn(crasher, KeyError)
            nursery.spawn(crasher, ValueError)

    with pytest.raises(_core.MultiError) as excinfo:
        _core.run(main)
    assert set(type(exc) for exc in excinfo.value.exceptions) == {
        ValueError, KeyError}


async def test_reschedule():
    async def child1():
        print("child1 start")
        x = await sleep_forever()
        print("child1 woke")
        assert x == 0
        print("child1 rescheduling t2")
        _core.reschedule(t2, _core.Error(ValueError()))
        print("child1 exit")

    async def child2():
        print("child2 start")
        _core.reschedule(t1, _core.Value(0))
        print("child2 sleep")
        with pytest.raises(ValueError):
            await sleep_forever()
        print("child2 successful exit")

    async with _core.open_nursery() as nursery:
        t1 = nursery.spawn(child1)
        # let t1 run and fall asleep
        await _core.yield_briefly()
        t2 = nursery.spawn(child2)


async def test_task_monitor():
    async def child():
        return 1

    q1 = _core.UnboundedQueue()
    q2 = _core.UnboundedQueue()
    q3 = _core.UnboundedQueue()
    async with _core.open_nursery() as nursery:
        task = nursery.spawn(child)
        task.add_monitor(q1)
        task.add_monitor(q2)

        # okay to discard one that was never there
        task.discard_monitor(q3)

        # discard one that *was* there, to make sure it works
        task.discard_monitor(q2)

        # add one that's already there:
        with pytest.raises(ValueError):
            task.add_monitor(q1)

        task.add_monitor(q3)

        # q1 and q3 should be there now, check that they indeed get notified
        await _core.wait_run_loop_idle()

        assert task.result.unwrap() == 1
        assert q1.get_all_nowait() == [task]
        with pytest.raises(_core.WouldBlock):
            q2.get_all_nowait()
        assert q3.get_all_nowait() == [task]

    # can re-add the queue now
    for _ in range(2):
        assert q1.empty()
        task.add_monitor(q1)
        # and it immediately receives the result:
        assert q1.get_all_nowait() == [task]
        # and since it was used, it's already gone from the set, so we can
        # loop around and do it again


async def test_bad_monitor_object():
    task = _core.current_task()

    with pytest.raises(TypeError):
        task.add_monitor("hello")

    class BadQueue:
        def put_nowait(self, obj):
            raise KeyError
    bad_queue = BadQueue()
    with pytest.raises(TypeError):
        task.add_monitor(bad_queue)


async def test_current_time():
    t1 = _core.current_time()
    # Windows clock is pretty low-resolution -- appveyor tests fail unless we
    # sleep for a bit here.
    time.sleep(time.get_clock_info("monotonic").resolution)
    t2 = _core.current_time()
    assert t1 < t2


async def test_current_time_with_mock_clock(mock_clock):
    start = mock_clock.current_time()
    assert mock_clock.current_time() == _core.current_time()
    assert mock_clock.current_time() == _core.current_time()
    mock_clock.advance(3.14)
    assert start + 3.14 == mock_clock.current_time() == _core.current_time()


async def test_current_task():
    async def child():
        return _core.current_task()

    async with _core.open_nursery() as nursery:
        child_task = nursery.spawn(child)
    assert child_task == child_task.result.unwrap()


async def test_current_statistics(mock_clock):
    # Just so there's some interesting stats:
    async def child():
        try:
            await sleep_forever()
        except _core.Cancelled:
            pass
    stats = _core.current_statistics()
    print(stats)
    # 2 system tasks + us
    assert stats.tasks_living == 3
    assert stats.call_soon_queue_size == 0

    async with _core.open_nursery() as nursery:
        task = nursery.spawn(child)
        await wait_run_loop_idle()
        _core.current_call_soon_thread_and_signal_safe()(lambda: None)
        stats = _core.current_statistics()
        print(stats)
        # 2 system tasks + us + child
        assert stats.tasks_living == 4
        # the exact value here might shift if we change how we do accounting
        # (currently it only counts tasks that we already know will be
        # runnable on the next pass), but still useful to at least test the
        # difference between now and after we wake up the child:
        assert stats.tasks_runnable == 0
        assert stats.call_soon_queue_size == 1

        nursery.cancel_scope.cancel()
        stats = _core.current_statistics()
        print(stats)
        assert stats.tasks_runnable == 1

    # Give the child a chance to die and the call_soon a chance to clear
    await _core.yield_briefly()
    await _core.yield_briefly()

    with _core.open_cancel_scope(deadline=_core.current_time() + 5) as scope:
        stats = _core.current_statistics()
        print(stats)
        assert stats.seconds_to_next_deadline == 5
    stats = _core.current_statistics()
    print(stats)
    assert stats.seconds_to_next_deadline == inf


@attr.s(slots=True, cmp=False, hash=False)
class TaskRecorder:
    record = attr.ib(default=attr.Factory(list))

    def task_scheduled(self, task):
        self.record.append(("schedule", task))

    def before_task_step(self, task):
        assert task is _core.current_task()
        self.record.append(("before", task))

    def after_task_step(self, task):
        assert task is _core.current_task()
        self.record.append(("after", task))

    def close(self):
        self.record.append(("close",))

    def filter_tasks(self, tasks):
        for item in self.record:
            if item[0] in ("schedule", "before", "after") and item[1] in tasks:
                yield item
            if item[0] == "close":
                yield item

def test_instruments():
    r1 = TaskRecorder()
    r2 = TaskRecorder()
    r3 = TaskRecorder()

    async def main():
        for _ in range(4):
            await _core.yield_briefly()
        cp = _core.current_instruments()
        assert cp == [r1, r2]
        # replace r2 with r3, to test that we can manipulate them as we go
        cp[1] = r3
        for _ in range(1):
            await _core.yield_briefly()
        return _core.current_task()
    task = _core.run(main, instruments=[r1, r2])
    # It sleeps 5 times, so it runs 6 times
    expected = (6 * [("schedule", task), ("before", task), ("after", task)]
                + [("close",)])
    assert len(r1.record) > len(r2.record) > len(r3.record)
    assert r1.record == r2.record + r3.record
    # Need to filter b/c there's also the system task bumping around in the
    # record:
    assert list(r1.filter_tasks([task])) == expected

def test_instruments_interleave():
    tasks = {}

    async def two_step1():
        await _core.yield_briefly()
    async def two_step2():
        await _core.yield_briefly()

    async def main():
        async with _core.open_nursery() as nursery:
            tasks["t1"] = nursery.spawn(two_step1)
            tasks["t2"] = nursery.spawn(two_step2)

    r = TaskRecorder()
    _core.run(main, instruments=[r])

    expected = [
        ("schedule", tasks["t1"]),
        ("schedule", tasks["t2"]),
        {("before", tasks["t1"]),
         ("after", tasks["t1"]),
         ("before", tasks["t2"]),
         ("after", tasks["t2"])},
        {("schedule", tasks["t1"]),
         ("before", tasks["t1"]),
         ("after", tasks["t1"]),
         ("schedule", tasks["t2"]),
         ("before", tasks["t2"]),
         ("after", tasks["t2"])},
        ("close",)]
    print(list(r.filter_tasks(tasks.values())))
    check_sequence_matches(list(r.filter_tasks(tasks.values())), expected)


def test_null_instrument():
    # undefined instrument methods are skipped
    class NullInstrument:
        pass

    async def main():
        await _core.yield_briefly()

    _core.run(main, instruments=[NullInstrument()])

# This test also tests having a crash before the initial task is even spawned,
# which is very difficult to handle.
def test_instruments_crash(capfd):
    record = []

    class BrokenInstrument:
        def task_scheduled(self, task):
            record.append("scheduled")
            raise ValueError("oops")

        def close(self):
            # Shouldn't be called -- tests that the instrument disabling logic
            # works right.
            record.append("closed")  # pragma: no cover

    async def main():
        record.append("main ran")
        return _core.current_task()

    r = TaskRecorder()
    main_task = _core.run(main, instruments=[r, BrokenInstrument()])
    assert record == ["scheduled", "main ran"]
    # the TaskRecorder kept going throughout, even though the BrokenInstrument
    # was disabled
    assert ("after", main_task) in r.record
    assert ("close",) in r.record
    # And we got a traceback on stderr
    out, err = capfd.readouterr()
    assert "ValueError: oops" in err
    assert "Instrument has been disabled" in err


def test_cancel_points():
    async def main1():
        with _core.open_cancel_scope() as scope:
            await _core.yield_if_cancelled()
            scope.cancel()
            with pytest.raises(_core.Cancelled):
                await _core.yield_if_cancelled()
    _core.run(main1)

    async def main2():
        with _core.open_cancel_scope() as scope:
            await _core.yield_briefly()
            scope.cancel()
            with pytest.raises(_core.Cancelled):
                await _core.yield_briefly()
    _core.run(main2)

    async def main3():
        with _core.open_cancel_scope() as scope:
            scope.cancel()
            with pytest.raises(_core.Cancelled):
                await sleep_forever()
    _core.run(main3)

    async def main4():
        with _core.open_cancel_scope() as scope:
            scope.cancel()
            await _core.yield_briefly_no_cancel()
            await _core.yield_briefly_no_cancel()
            with pytest.raises(_core.Cancelled):
                await _core.yield_briefly()
    _core.run(main4)


async def test_cancel_edge_cases():
    with _core.open_cancel_scope() as scope:
        # Two cancels in a row -- idempotent
        scope.cancel()
        scope.cancel()
        await _core.yield_briefly()
    assert scope.cancel_called
    assert scope.cancel_caught

    with _core.open_cancel_scope() as scope:
        # Check level-triggering
        scope.cancel()
        with pytest.raises(_core.Cancelled):
            await sleep_forever()
        with pytest.raises(_core.Cancelled):
            await sleep_forever()


async def test_basic_timeout(mock_clock):
    start = _core.current_time()
    with _core.open_cancel_scope() as scope:
        assert scope.deadline == inf
        scope.deadline = start + 1
        assert scope.deadline == start + 1
    assert not scope.cancel_called
    mock_clock.advance(2)
    await _core.yield_briefly()
    await _core.yield_briefly()
    await _core.yield_briefly()
    assert not scope.cancel_called

    start = _core.current_time()
    with _core.open_cancel_scope(deadline=start + 1) as scope:
        mock_clock.advance(2)
        await sleep_forever()
    # But then the scope swallowed the exception... but we can still see it
    # here:
    assert scope.cancel_called
    assert scope.cancel_caught

    # changing deadline
    start = _core.current_time()
    with _core.open_cancel_scope() as scope:
        await _core.yield_briefly()
        scope.deadline = start + 10
        await _core.yield_briefly()
        mock_clock.advance(5)
        await _core.yield_briefly()
        scope.deadline = start + 1
        with pytest.raises(_core.Cancelled):
            await _core.yield_briefly()
        with pytest.raises(_core.Cancelled):
            await _core.yield_briefly()

async def test_cancel_scope_nesting():
    # Nested scopes: if two triggering at once, the outer one wins
    with _core.open_cancel_scope() as scope1:
        with _core.open_cancel_scope() as scope2:
            with _core.open_cancel_scope() as scope3:
                scope3.cancel()
                scope2.cancel()
                await sleep_forever()
    assert scope3.cancel_called
    assert not scope3.cancel_caught
    assert scope2.cancel_called
    assert scope2.cancel_caught
    assert not scope1.cancel_called
    assert not scope1.cancel_caught

    # shielding
    with _core.open_cancel_scope() as scope1:
        with _core.open_cancel_scope() as scope2:
            scope1.cancel()
            with pytest.raises(_core.Cancelled):
                await _core.yield_briefly()
            with pytest.raises(_core.Cancelled):
                await _core.yield_briefly()
            scope2.shield = True
            await _core.yield_briefly()
            scope2.cancel()
            with pytest.raises(_core.Cancelled):
                await _core.yield_briefly()

    # if a scope is pending, but then gets popped off the stack, then it
    # isn't delivered
    with _core.open_cancel_scope() as scope:
        scope.cancel()
        await _core.yield_briefly_no_cancel()
    await _core.yield_briefly()
    assert not scope.cancel_caught


async def test_timekeeping():
    # probably a good idea to use a real clock for *one* test anyway...
    TARGET = 0.25
    # give it a few tries in case of random CI server flakiness
    for _ in range(4):
        real_start = time.monotonic()
        with _core.open_cancel_scope() as scope:
            scope.deadline = _core.current_time() + TARGET
            await sleep_forever()
        real_duration = time.monotonic() - real_start
        accuracy = real_duration / TARGET
        print(accuracy)
        # Actual time elapsed should always be >= target time
        # (== is possible because time.monotonic on Windows is really low res)
        if 1.0 <= accuracy < 1.2:  # pragma: no branch
            break
    else:  # pragma: no cover
        assert False


async def test_failed_abort():
    stubborn_scope = [None]
    record = []
    async def stubborn_sleeper():
        with _core.open_cancel_scope() as scope:
            stubborn_scope[0] = scope
            record.append("sleep")
            x = await _core.yield_indefinitely(lambda: _core.Abort.FAILED)
            assert x == 1
            record.append("woke")
            try:
                await _core.yield_if_cancelled()
            except _core.Cancelled:
                record.append("cancelled")

    async with _core.open_nursery() as nursery:
        task = nursery.spawn(stubborn_sleeper)
        await busy_wait_for(lambda: record)
        stubborn_scope[0].cancel()
        await _core.yield_briefly()
        await _core.yield_briefly()
        await _core.yield_briefly()
        _core.reschedule(task, _core.Value(1))
    assert record == ["sleep", "woke", "cancelled"]


def test_broken_abort():
    async def main():
        # These yields are here to work around an annoying warning -- we're
        # going to crash the main loop, and if we (by chance) do this before
        # the call_soon_task runs for the first time, then Python gives us a
        # spurious warning about it not being awaited. (I mean, the warning is
        # correct, but here we're testing our ability to deliver a
        # semi-meaningful error after things have gone totally pear-shaped, so
        # it's not relevant.)  By letting the call_soon_task run first, we
        # avoid the warning.
        await _core.yield_briefly()
        await _core.yield_briefly()
        with _core.open_cancel_scope() as scope:
            scope.cancel()
            # None is not a legal return value here
            await _core.yield_indefinitely(lambda: None)
    with pytest.raises(_core.TrioInternalError):
        _core.run(main)


async def test_spawn_system_task():
    record = []
    async def system_task(x):
        record.append(("x", x))
        record.append(("ki", _core.ki_protected()))
        await _core.yield_briefly()
    task = _core.spawn_system_task(system_task, 1)
    await task.wait()
    assert record == [("x", 1), ("ki", True)]

# intentionally make a system task crash (simulates a bug in call_soon_task or
# similar)
def test_system_task_crash():
    async def crasher():
        raise KeyError

    async def main():
        task = _core.spawn_system_task(crasher)
        task.wait()

    with pytest.raises(_core.TrioInternalError):
        _core.run(main)


# This used to fail because yield_briefly was a yield followed by an immediate
# reschedule. So we had:
# 1) this task yields
# 2) this task is rescheduled
# ...
# 3) next iteration of event loop starts, runs timeouts
# 4) this task has timed out
# 5) ...but it's on the run queue, so the timeout is queued to be delivered
#    the next time that it's blocked.
async def test_yield_briefly_checks_for_timeout(mock_clock):
    with _core.open_cancel_scope(deadline=_core.current_time() + 5) as scope:
        await _core.yield_briefly()
        with pytest.raises(_core.Cancelled):
            mock_clock.advance(10)
            await _core.yield_briefly()


# This tests that sys.exc_info is properly saved/restored as we swap between
# tasks. It turns out that the interpreter automagically handles this for us
# so there's no special code in trio required to pass this test, but it's
# still nice to know that it works :-)
async def test_exc_info():
    record = []

    async def child1():
        with pytest.raises(ValueError) as excinfo:
            try:
                record.append("child1 raise")
                raise ValueError("child1")
            except ValueError:
                record.append("child1 sleep")
                await busy_wait_for(lambda: "child2 wake" in record)
                record.append("child1 re-raise")
                raise
        assert excinfo.value.__context__ is None
        record.append("child1 success")

    async def child2():
        with pytest.raises(KeyError) as excinfo:
            await busy_wait_for(lambda: record)
            record.append("child2 wake")
            assert sys.exc_info() == (None, None, None)
            try:
                raise KeyError("child2")
            except KeyError:
                record.append("child2 sleep again")
                await busy_wait_for(lambda: "child1 re-raise" in record)
                record.append("child2 re-raise")
                raise
        assert excinfo.value.__context__ is None
        record.append("child2 success")

    async with _core.open_nursery() as nursery:
        nursery.spawn(child1)
        nursery.spawn(child2)

    assert record == ["child1 raise", "child1 sleep",
                      "child2 wake", "child2 sleep again",
                      "child1 re-raise", "child1 success",
                      "child2 re-raise", "child2 success"]


async def test_call_soon_basic():
    record = []
    def cb(x):
        record.append(("cb", x))
    call_soon = _core.current_call_soon_thread_and_signal_safe()
    call_soon(cb, 1)
    assert not record
    await busy_wait_for(lambda: len(record) == 1)
    assert record == [("cb", 1)]

def test_call_soon_too_late():
    call_soon = None
    async def main():
        nonlocal call_soon
        call_soon = _core.current_call_soon_thread_and_signal_safe()
    _core.run(main)
    assert call_soon is not None
    with pytest.raises(_core.RunFinishedError):
        call_soon(lambda: None)  # pragma: no branch

def test_call_soon_after_crash():
    record = []

    async def main():
        call_soon = _core.current_call_soon_thread_and_signal_safe()
        # After main exits but before finally cleaning up, callback processed
        # normally
        call_soon(lambda: record.append("sync-cb"))
        raise ValueError

    with pytest.raises(ValueError):
        _core.run(main)

    assert record == ["sync-cb"]

@pytest.mark.foo
def test_call_soon_crashes():
    record = []

    async def main():
        call_soon = _core.current_call_soon_thread_and_signal_safe()
        call_soon(lambda: dict()["nope"])
        try:
            await sleep_forever()
        except _core.Cancelled:
            record.append("cancelled!")

    with pytest.raises(_core.TrioInternalError) as excinfo:
        _core.run(main)

    assert type(excinfo.value.__cause__) is KeyError
    assert record == ["cancelled!"]

def test_call_soon_starvation_resistance():
    # Even if we push callbacks in from callbacks, so that the callback queue
    # never empties out, then we still can't starve out other tasks from
    # running.
    call_soon = None
    record = []

    def naughty_cb(i):
        nonlocal call_soon
        try:
            call_soon(naughty_cb, i + 1)
        except _core.RunFinishedError:
            record.append(("run finished", i))

    async def main():
        nonlocal call_soon
        call_soon = _core.current_call_soon_thread_and_signal_safe()
        call_soon(naughty_cb, 0)
        record.append("starting")
        for _ in range(20):
            await _core.yield_briefly()

    _core.run(main)
    assert len(record) == 2
    assert record[0] == "starting"
    assert record[1][0] == "run finished"
    assert record[1][1] >= 20

def test_call_soon_threaded_stress_test():
    cb_counter = 0
    def cb():
        nonlocal cb_counter
        cb_counter += 1

    def stress_thread(call_soon):
        try:
            while True:
                call_soon(cb)
        except _core.RunFinishedError:
            pass

    async def main():
        call_soon = _core.current_call_soon_thread_and_signal_safe()
        thread = threading.Thread(target=stress_thread, args=(call_soon,))
        thread.start()
        for _ in range(3):
            start_value = cb_counter
            await busy_wait_for(lambda: cb_counter > start_value)

    _core.run(main)
    print(cb_counter)

async def test_call_soon_massive_queue():
    # There are edge cases in the Unix wakeup pipe code when the pipe buffer
    # overflows, so let's try to make that happen. On Linux the default pipe
    # buffer size is 64 KiB (though we reduce it to 4096). This also serves as
    # a good stress test of the Windows code.
    COUNT = 66000
    call_soon = _core.current_call_soon_thread_and_signal_safe()
    counter = [0]
    def cb():
        counter[0] += 1
    for _ in range(COUNT):
        call_soon(cb)
    await busy_wait_for(lambda: counter[0] == COUNT)


# make sure to set up one where all tasks are blocked on I/O to exercise the
# timeout = _MAX_TIMEOUT line

# other files:
# unix IO
# windows IO
