import threading
import sys
import time
from math import inf
import platform
import functools

import pytest
import attr

from .tutil import check_sequence_matches
from ...testing import (
    wait_all_tasks_blocked, Sequencer, assert_yields,
)
from ..._timeouts import sleep

from ... import _core

# slightly different from _timeouts.sleep_forever because it returns the value
# its rescheduled with, which is really only useful for tests of
# rescheduling...
async def sleep_forever():
    return await _core.yield_indefinitely(lambda _: _core.Abort.SUCCEEDED)

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


async def test_reap_bad_task():
    async def child():
        pass
    async with _core.open_nursery() as nursery:
        t = nursery.spawn(child)
        with pytest.raises(ValueError):
            nursery.reap(None)
        with pytest.raises(ValueError):
            nursery.reap(t)
        await t.wait()
        nursery.reap(t)
        with pytest.raises(ValueError):
            nursery.reap(t)


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
        await _core.wait_all_tasks_blocked()

        assert task.result.unwrap() == 1
        assert q1.get_batch_nowait() == [task]
        with pytest.raises(_core.WouldBlock):
            q2.get_batch_nowait()
        assert q3.get_batch_nowait() == [task]

    # can re-add the queue now
    for _ in range(2):
        assert q1.empty()
        task.add_monitor(q1)
        # and it immediately receives the result:
        assert q1.get_batch_nowait() == [task]
        # and since it was used, it's already gone from the set, so we can
        # loop around and do it again


async def test_bad_monitor_object():
    task = _core.current_task()

    with pytest.raises(TypeError):
        task.add_monitor("hello")

    class BadQueue:
        def put_nowait(self, obj):  # pragma: no cover
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
    mock_clock.jump(3.14)
    assert start + 3.14 == mock_clock.current_time() == _core.current_time()


async def test_current_clock(mock_clock):
    assert mock_clock is _core.current_clock()


async def test_current_task():
    async def child():
        return _core.current_task()

    async with _core.open_nursery() as nursery:
        child_task = nursery.spawn(child)
    assert child_task == child_task.result.unwrap()


def test_out_of_context():
    with pytest.raises(RuntimeError):
        _core.current_task()
    with pytest.raises(RuntimeError):
        _core.current_time()


async def test_current_statistics(mock_clock):
    # Make sure all the early startup stuff has settled down
    await wait_all_tasks_blocked()

    # A child that sticks around to make some interesting stats:
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
        await wait_all_tasks_blocked()
        call_soon = _core.current_call_soon_thread_and_signal_safe()
        call_soon(lambda: None)
        call_soon(lambda: None, idempotent=True)
        stats = _core.current_statistics()
        print(stats)
        # 2 system tasks + us + child
        assert stats.tasks_living == 4
        # the exact value here might shift if we change how we do accounting
        # (currently it only counts tasks that we already know will be
        # runnable on the next pass), but still useful to at least test the
        # difference between now and after we wake up the child:
        assert stats.tasks_runnable == 0
        assert stats.call_soon_queue_size == 2

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

    def before_run(self):
        self.record.append(("before_run",))

    def task_scheduled(self, task):
        self.record.append(("schedule", task))

    def before_task_step(self, task):
        assert task is _core.current_task()
        self.record.append(("before", task))

    def after_task_step(self, task):
        assert task is _core.current_task()
        self.record.append(("after", task))

    def after_run(self):
        self.record.append(("after_run",))

    def filter_tasks(self, tasks):
        for item in self.record:
            if item[0] in ("schedule", "before", "after") and item[1] in tasks:
                yield item
            if item[0] in ("before_run", "after_run"):
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
    expected = (
        [("before_run",)]
        + 6 * [("schedule", task), ("before", task), ("after", task)]
        + [("after_run",)])
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
        ("before_run",),
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
        ("after_run",)]
    print(list(r.filter_tasks(tasks.values())))
    check_sequence_matches(list(r.filter_tasks(tasks.values())), expected)


def test_null_instrument():
    # undefined instrument methods are skipped
    class NullInstrument:
        pass

    async def main():
        await _core.yield_briefly()

    _core.run(main, instruments=[NullInstrument()])


def test_instrument_before_after_run():
    record = []
    class BeforeAfterRun:
        def before_run(self):
            record.append("before_run")
        def after_run(self):
            record.append("after_run")
    async def main():
        pass
    _core.run(main, instruments=[BeforeAfterRun()])
    assert record == ["before_run", "after_run"]


def test_instrument_task_spawn_exit():
    record = []
    class SpawnExitRecorder:
        def task_spawned(self, task):
            record.append(("spawned", task))
        def task_exited(self, task):
            record.append(("exited", task))

    async def main():
        return _core.current_task()

    main_task = _core.run(main, instruments=[SpawnExitRecorder()])
    assert ("spawned", main_task) in record
    assert ("exited", main_task) in record

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
    assert ("after_run",) in r.record
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
    assert scope.cancelled_caught

    with _core.open_cancel_scope() as scope:
        # Check level-triggering
        scope.cancel()
        with pytest.raises(_core.Cancelled) as excinfo1:
            await sleep_forever()
        with pytest.raises(_core.Cancelled) as excinfo2:
            await sleep_forever()
        # Same exception both times, to ensure complete tracebacks:
        assert excinfo1.value is excinfo2.value


async def test_cancel_scope_multierror_filtering():
    async def child():
        await sleep_forever()
    async def crasher():
        raise KeyError

    try:
        with _core.open_cancel_scope() as outer:
            try:
                async with _core.open_nursery() as nursery:
                    # Two children that get cancelled by the nursery scope
                    t1 = nursery.spawn(child)
                    t2 = nursery.spawn(child)
                    nursery.cancel_scope.cancel()
                    with _core.open_cancel_scope(shield=True):
                        # Make sure they receive the inner cancellation
                        # exception before we cancel the outer scope
                        await t1.wait()
                        await t2.wait()
                    # One child that gets cancelled by the outer scope
                    t3 = nursery.spawn(child)
                    outer.cancel()
                    # And one that raises a different error
                    t4 = nursery.spawn(crasher)
            except _core.MultiError as multi_exc:
                # This is outside the nursery scope but inside the outer
                # scope, so the nursery should have absorbed t1 and t2's
                # exceptions but t3 and t4 should remain
                assert len(multi_exc.exceptions) == 2
                summary = {}
                for exc in multi_exc.exceptions:
                    summary.setdefault(type(exc), 0)
                    summary[type(exc)] += 1
                assert summary == {_core.Cancelled: 1, KeyError: 1}
                raise
    except BaseException as exc:
        # This is ouside the outer scope, so t3's Cancelled exception should
        # also have been absorbed, leaving just a regular KeyError from
        # crasher()
        assert type(exc) is KeyError
    else:
        assert False  # pragma: no cover


async def test_precancelled_task():
    # a task that gets spawned into an already-cancelled nursery should begin
    # execution (https://github.com/python-trio/trio/issues/41), but get a
    # cancelled error at its first blocking call.
    record = []
    async def blocker():
        record.append("started")
        await sleep_forever()
    async with _core.open_nursery() as nursery:
        nursery.cancel_scope.cancel()
        nursery.spawn(blocker)
    assert record == ["started"]


async def test_cancel_shielding():
    with _core.open_cancel_scope() as outer:
        with _core.open_cancel_scope() as inner:
            await _core.yield_briefly()
            outer.cancel()
            with pytest.raises(_core.Cancelled):
                await _core.yield_briefly()

            assert inner.shield is False
            with pytest.raises(TypeError):
                inner.shield = "hello"
            assert inner.shield is False

            inner.shield = True
            assert inner.shield is True
            # shield protects us from 'outer'
            await _core.yield_briefly()

            with _core.open_cancel_scope() as innerest:
                innerest.cancel()
                # but it doesn't protect us from scope inside inner
                with pytest.raises(_core.Cancelled):
                    await _core.yield_briefly()
            await _core.yield_briefly()

            inner.shield = False
            # can disable shield again
            with pytest.raises(_core.Cancelled):
                await _core.yield_briefly()

            # re-enable shield
            inner.shield = True
            await _core.yield_briefly()
            # shield doesn't protect us from inner itself
            inner.cancel()
            # This should now raise, but be absorbed by the inner scope
            await _core.yield_briefly()
        assert inner.cancelled_caught


# make sure that cancellation propagates immediately to all children
async def test_cancel_inheritance():
    record = set()
    async def leaf(ident):
        try:
            await sleep_forever()
        except _core.Cancelled:
            record.add(ident)
    async def worker(ident):
        async with _core.open_nursery() as nursery:
            t1 = nursery.spawn(leaf, ident + "-l1")
            t2 = nursery.spawn(leaf, ident + "-l2")
            with _core.open_cancel_scope(shield=True):
                await t1.wait()
                await t2.wait()
    async with _core.open_nursery() as nursery:
        w1 = nursery.spawn(worker, "w1")
        w2 = nursery.spawn(worker, "w2")
        nursery.cancel_scope.cancel()
        with _core.open_cancel_scope(shield=True):
            await w1.wait()
            await w2.wait()
            assert record == {"w1-l1", "w1-l2", "w2-l1", "w2-l2"}


async def test_cancel_shield_abort():
    with _core.open_cancel_scope() as outer:
        async with _core.open_nursery() as nursery:
            outer.cancel()
            nursery.cancel_scope.shield = True
            # The outer scope is cancelled, but this task is protected by the
            # shield, so it manages to get to sleep
            record = []
            async def sleeper():
                record.append("sleeping")
                try:
                    await sleep_forever()
                except _core.Cancelled:
                    record.append("cancelled")
            task = nursery.spawn(sleeper)
            await wait_all_tasks_blocked()
            assert record == ["sleeping"]
            # now when we unshield, it should abort the sleep.
            nursery.cancel_scope.shield = False
            # wait for the task to finish before entering the nursery
            # __aexit__, because __aexit__ could make it spuriously look like
            # this worked by cancelling the nursery scope. (When originally
            # written, without these last few lines, the test spuriously
            # passed, even though shield assignment was buggy.)
            with _core.open_cancel_scope(shield=True):
                await task.wait()

async def test_basic_timeout(mock_clock):
    start = _core.current_time()
    with _core.open_cancel_scope() as scope:
        assert scope.deadline == inf
        scope.deadline = start + 1
        assert scope.deadline == start + 1
    assert not scope.cancel_called
    mock_clock.jump(2)
    await _core.yield_briefly()
    await _core.yield_briefly()
    await _core.yield_briefly()
    assert not scope.cancel_called

    start = _core.current_time()
    with _core.open_cancel_scope(deadline=start + 1) as scope:
        mock_clock.jump(2)
        await sleep_forever()
    # But then the scope swallowed the exception... but we can still see it
    # here:
    assert scope.cancel_called
    assert scope.cancelled_caught

    # changing deadline
    start = _core.current_time()
    with _core.open_cancel_scope() as scope:
        await _core.yield_briefly()
        scope.deadline = start + 10
        await _core.yield_briefly()
        mock_clock.jump(5)
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
    assert not scope3.cancelled_caught
    assert scope2.cancel_called
    assert scope2.cancelled_caught
    assert not scope1.cancel_called
    assert not scope1.cancelled_caught

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
    assert not scope.cancelled_caught


async def test_timekeeping():
    # probably a good idea to use a real clock for *one* test anyway...
    TARGET = 0.1
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
        if 1.0 <= accuracy < 2:  # pragma: no branch
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
            x = await _core.yield_indefinitely(lambda _: _core.Abort.FAILED)
            assert x == 1
            record.append("woke")
            try:
                await _core.yield_if_cancelled()
            except _core.Cancelled:
                record.append("cancelled")

    async with _core.open_nursery() as nursery:
        task = nursery.spawn(stubborn_sleeper)
        await wait_all_tasks_blocked()
        assert record == ["sleep"]
        stubborn_scope[0].cancel()
        await wait_all_tasks_blocked()
        # cancel didn't wake it up
        assert record == ["sleep"]
        # wake it up again by hand
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
            await _core.yield_indefinitely(lambda _: None)
    with pytest.raises(_core.TrioInternalError):
        _core.run(main)

    # Because this crashes, various __del__ methods print complaints on
    # stderr. Make sure that they get run now, so the output is attached to
    # this test.
    import gc
    gc.collect()


def test_error_in_run_loop():
    # Blow stuff up real good to check we at least get a TrioInternalError
    async def main():
        task = _core.current_task()
        task._schedule_points = "hello!"
        await _core.yield_briefly()

    with pytest.raises(_core.TrioInternalError):
        _core.run(main)

    # Make sure any warnings etc. are associated with this test
    import gc
    gc.collect()


async def test_spawn_system_task():
    record = []
    async def system_task(x):
        record.append(("x", x))
        record.append(("ki", _core.currently_ki_protected()))
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
        await task.wait()

    with pytest.raises(_core.TrioInternalError):
        _core.run(main)

def test_system_task_crash_MultiError():
    async def crasher1():
        raise KeyError

    async def crasher2():
        raise ValueError

    async def system_task():
        async with _core.open_nursery() as nursery:
            nursery.spawn(crasher1)
            nursery.spawn(crasher2)

    async def main():
        _core.spawn_system_task(system_task)
        await sleep_forever()

    with pytest.raises(_core.MultiError) as excinfo:
        _core.run(main)

    assert len(excinfo.value.exceptions) == 2
    cause_types = set()
    for exc in excinfo.value.exceptions:
        assert type(exc) is _core.TrioInternalError
        cause_types.add(type(exc.__cause__ ))
    assert cause_types == {KeyError, ValueError}

def test_system_task_crash_plus_Cancelled():
    # Set up a situation where a system task crashes with a
    # MultiError([Cancelled, ValueError])
    async def crasher():
        try:
            await sleep_forever()
        except _core.Cancelled:
            raise ValueError

    async def cancelme():
        await sleep_forever()

    async def system_task():
        async with _core.open_nursery() as nursery:
            nursery.spawn(crasher)
            nursery.spawn(cancelme)

    async def main():
        _core.spawn_system_task(system_task)
        # then we exit, triggering a cancellation

    with pytest.raises(_core.TrioInternalError) as excinfo:
        _core.run(main)
    assert type(excinfo.value.__cause__) is ValueError

def test_system_task_crash_KeyboardInterrupt():
    async def ki():
        raise KeyboardInterrupt

    async def main():
        _core.spawn_system_task(ki)
        await sleep_forever()

    # KI doesn't get wrapped with TrioInternalError
    with pytest.raises(KeyboardInterrupt):
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
            mock_clock.jump(10)
            await _core.yield_briefly()


# This tests that sys.exc_info is properly saved/restored as we swap between
# tasks. It turns out that the interpreter automagically handles this for us
# so there's no special code in trio required to pass this test, but it's
# still nice to know that it works :-).
#
# Update: it turns out I was right to be nervous! see the next test...
async def test_exc_info():
    record = []
    seq = Sequencer()

    async def child1():
        with pytest.raises(ValueError) as excinfo:
            try:
                async with seq(0):
                    pass  # we don't yield until seq(2) below
                record.append("child1 raise")
                raise ValueError("child1")
            except ValueError:
                record.append("child1 sleep")
                async with seq(2):
                    pass
                assert "child2 wake" in record
                record.append("child1 re-raise")
                raise
        assert excinfo.value.__context__ is None
        record.append("child1 success")

    async def child2():
        with pytest.raises(KeyError) as excinfo:
            async with seq(1):
                pass  # we don't yield until seq(3) below
            assert "child1 sleep" in record
            record.append("child2 wake")
            assert sys.exc_info() == (None, None, None)
            try:
                raise KeyError("child2")
            except KeyError:
                record.append("child2 sleep again")
                async with seq(3):
                    pass
                assert "child1 re-raise" in record
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


# At least as of CPython 3.6, using .throw() to raise an exception inside a
# coroutine/generator causes the original exc_info state to be lost, so things
# like re-raising and exception chaining are broken.
#
# https://bugs.python.org/issue29587
async def test_exc_info_after_yield_error():
    async def child():
        try:
            raise KeyError
        except Exception:
            try:
                await sleep_forever()
            except Exception:
                pass
            raise

    async with _core.open_nursery() as nursery:
        t = nursery.spawn(child)
        await wait_all_tasks_blocked()
        _core.reschedule(t, _core.Error(ValueError()))
        await t.wait()
        with pytest.raises(KeyError):
            nursery.reap_and_unwrap(t)


# Similar to previous test -- if the ValueError() gets sent in via 'throw',
# then Python's normal implicit chaining stuff is broken. We have to
async def test_exception_chaining_after_yield_error():
    async def child():
        try:
            raise KeyError
        except Exception:
            await sleep_forever()

    async with _core.open_nursery() as nursery:
        t = nursery.spawn(child)
        await wait_all_tasks_blocked()
        _core.reschedule(t, _core.Error(ValueError()))
        await t.wait()
        with pytest.raises(ValueError) as excinfo:
            nursery.reap_and_unwrap(t)
        assert isinstance(excinfo.value.__context__, KeyError)


async def test_call_soon_basic():
    record = []
    def cb(x):
        record.append(("cb", x))
    call_soon = _core.current_call_soon_thread_and_signal_safe()
    call_soon(cb, 1)
    assert not record
    await wait_all_tasks_blocked()
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


async def test_call_soon_idempotent():
    record = []
    def cb(x):
        record.append(x)

    call_soon = _core.current_call_soon_thread_and_signal_safe()
    call_soon(cb, 1)
    call_soon(cb, 1, idempotent=True)
    call_soon(cb, 1, idempotent=True)
    call_soon(cb, 1, idempotent=True)
    call_soon(cb, 2, idempotent=True)
    call_soon(cb, 2, idempotent=True)
    await wait_all_tasks_blocked()
    assert len(record) == 3
    assert sorted(record) == [1, 1, 2]

    # ordering test
    record = []
    for _ in range(3):
        for i in range(100):
            call_soon(cb, i, idempotent=True)
    await wait_all_tasks_blocked()
    if (sys.version_info < (3, 6)
          and platform.python_implementation() == "CPython"):
        # no order guarantees
        record.sort()
    # Otherwise, we guarantee FIFO
    assert record == list(range(100))

def test_call_soon_idempotent_requeue():
    # We guarantee that if a call has finished, queueing it again will call it
    # again. Due to the lack of synchronization, this effectively means that
    # we have to guarantee that once a call has *started*, queueing it again
    # will call it again. Also this is much easier to test :-)
    record = []

    def redo(call_soon):
        record.append(None)
        try:
            call_soon(redo, call_soon, idempotent=True)
        except _core.RunFinishedError:
            pass

    async def main():
        call_soon = _core.current_call_soon_thread_and_signal_safe()
        call_soon(redo, call_soon, idempotent=True)
        await _core.yield_briefly()
        await _core.yield_briefly()
        await _core.yield_briefly()

    _core.run(main)

    assert len(record) >= 2

def test_call_soon_after_main_crash():
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


def test_call_soon_crashes():
    record = set()

    async def main():
        call_soon = _core.current_call_soon_thread_and_signal_safe()
        call_soon(lambda: dict()["nope"])
        # check that a crashing call_soon callback doesn't stop further calls
        # to call_soon
        call_soon(lambda: record.add("2nd call_soon ran"))
        try:
            await sleep_forever()
        except _core.Cancelled:
            record.add("cancelled!")

    with pytest.raises(_core.TrioInternalError) as excinfo:
        _core.run(main)

    assert type(excinfo.value.__cause__) is KeyError
    assert record == {"2nd call_soon ran", "cancelled!"}


async def test_call_soon_FIFO():
    N = 100
    record = []
    call_soon = _core.current_call_soon_thread_and_signal_safe()
    for i in range(N):
        call_soon(lambda j: record.append(j), i)
    await wait_all_tasks_blocked()
    assert record == list(range(N))


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
                time.sleep(0)
        except _core.RunFinishedError:
            pass

    async def main():
        call_soon = _core.current_call_soon_thread_and_signal_safe()
        thread = threading.Thread(target=stress_thread, args=(call_soon,))
        thread.start()
        for _ in range(10):
            start_value = cb_counter
            while cb_counter == start_value:
                await sleep(0.01)

    _core.run(main)
    print(cb_counter)


async def test_call_soon_massive_queue():
    # There are edge cases in the wakeup fd code when the wakeup fd overflows,
    # so let's try to make that happen. This is also just a good stress test
    # in general. (With the current-as-of-2017-02-14 code using a socketpair
    # with minimal buffer, Linux takes 6 wakeups to fill the buffer and MacOS
    # takes 1 wakeup. So 1000 is overkill if anything. Windows OTOH takes
    # ~600,000 wakeups, but has the same code paths...)
    COUNT = 1000
    call_soon = _core.current_call_soon_thread_and_signal_safe()
    counter = [0]
    def cb(i):
        # This also tests FIFO ordering of callbacks
        assert counter[0] == i
        counter[0] += 1
    for i in range(COUNT):
        call_soon(cb, i)
    await wait_all_tasks_blocked()
    assert counter[0] == COUNT


async def test_slow_abort_basic():
    with _core.open_cancel_scope() as scope:
        scope.cancel()
        with pytest.raises(_core.Cancelled):
            task = _core.current_task()
            call_soon = _core.current_call_soon_thread_and_signal_safe()
            def slow_abort(raise_cancel):
                result = _core.Result.capture(raise_cancel)
                call_soon(_core.reschedule, task, result)
                return _core.Abort.FAILED
            await _core.yield_indefinitely(slow_abort)


async def test_slow_abort_edge_cases():
    record = []

    async def slow_aborter():
        task = _core.current_task()
        call_soon = _core.current_call_soon_thread_and_signal_safe()
        def slow_abort(raise_cancel):
            record.append("abort-called")
            result = _core.Result.capture(raise_cancel)
            call_soon(_core.reschedule, task, result)
            return _core.Abort.FAILED
        with pytest.raises(_core.Cancelled):
            record.append("sleeping")
            await _core.yield_indefinitely(slow_abort)
        record.append("cancelled")
        # blocking again, this time it's okay, because we're shielded
        await _core.yield_briefly()
        record.append("done")

    with _core.open_cancel_scope() as outer1:
        with _core.open_cancel_scope() as outer2:
            async with _core.open_nursery() as nursery:
                # So we have a task blocked on an operation that can't be
                # aborted immediately
                nursery.spawn(slow_aborter)
                await wait_all_tasks_blocked()
                assert record == ["sleeping"]
                # And then we cancel it, so the abort callback gets run
                outer1.cancel()
                assert record == ["sleeping", "abort-called"]
                # In fact that happens twice! (This used to cause the abort
                # callback to be run twice)
                outer2.cancel()
                assert record == ["sleeping", "abort-called"]
                # But then before the abort finishes, the task gets shielded!
                nursery.cancel_scope.shield = True
                # Now we wait for the task to finish...
            # The cancellation was delivered, even though it was shielded
            assert record == ["sleeping", "abort-called", "cancelled", "done"]


async def test_parent_task():
    async def child2():
        pass

    async def child1():
        async with _core.open_nursery() as nursery:
            return nursery.spawn(child2)

    async with _core.open_nursery() as nursery:
        t1 = nursery.spawn(child1)
        await t1.wait()
        t2 = t1.result.unwrap()

        assert t1.parent_task is _core.current_task()
        assert t2.parent_task is t1

    t = _core.current_task()
    # Make sure that chaining parent_task eventually gives None (and not, for
    # example, an error)
    while t is not None:
        t = t.parent_task


async def test_nursery_closure():
    async def child1(nursery):
        # We can add new tasks to the nursery even after entering __aexit__,
        # so long as there are still tasks running
        nursery.spawn(child2)
    async def child2():
        pass

    async with _core.open_nursery() as nursery:
        nursery.spawn(child1, nursery)

    # But once we've left __aexit__, the nursery is closed
    with pytest.raises(RuntimeError):
        nursery.spawn(child2)

async def test_spawn_name():
    async def func1():
        pass
    async def func2():  # pragma: no cover
        pass

    async with _core.open_nursery() as nursery:
        for spawn_fn in [nursery.spawn, _core.spawn_system_task]:
            t0 = spawn_fn(func1)
            assert "func1" in t0.name

            t1 = spawn_fn(func1, name=func2)
            assert "func2" in t1.name

            t2 = spawn_fn(func1, name="func3")
            assert "func3" == t2.name

            t3 = spawn_fn(functools.partial(func1))
            assert "func1" in t3.name

            t4 = spawn_fn(func1, name=object())
            assert "object" in t4.name


async def test_current_effective_deadline(mock_clock):
    assert _core.current_effective_deadline() == inf

    with _core.open_cancel_scope(deadline=5) as scope1:
        with _core.open_cancel_scope(deadline=10) as scope2:
            assert _core.current_effective_deadline() == 5
            scope2.deadline = 3
            assert _core.current_effective_deadline() == 3
            scope2.deadline = 10
            assert _core.current_effective_deadline() == 5
            scope2.shield = True
            assert _core.current_effective_deadline() == 10
            scope2.shield = False
            assert _core.current_effective_deadline() == 5
            scope1.cancel()
            assert _core.current_effective_deadline() == -inf
            scope2.shield = True
            assert _core.current_effective_deadline() == 10
        assert _core.current_effective_deadline() == -inf
    assert _core.current_effective_deadline() == inf


def test_nice_error_on_curio_style_run():
    async def f():
        pass

    coro = f()
    with pytest.raises(TypeError) as excinfo:
        _core.run(coro)
    assert "unexpected coroutine object" in str(excinfo.value)

    # consume the coroutine to avoid a warning message
    async def consume_it():
        await coro
    _core.run(consume_it)


async def test_trivial_yields():
    with assert_yields():
        await _core.yield_briefly()

    with assert_yields():
        await _core.yield_if_cancelled()
        await _core.yield_briefly_no_cancel()

    with assert_yields():
        async with _core.open_nursery():
            pass

    with _core.open_cancel_scope() as cancel_scope:
        cancel_scope.cancel()
        with pytest.raises(_core.MultiError) as excinfo:
            async with _core.open_nursery():
                raise KeyError
        assert len(excinfo.value.exceptions) == 2
        assert set(type(e) for e in excinfo.value.exceptions) == {
            KeyError, _core.Cancelled}

    async def trivial():
        pass
    async with _core.open_nursery() as nursery:
        t = nursery.spawn(trivial)
    assert t.result is not None
    with assert_yields():
        await t.wait()
