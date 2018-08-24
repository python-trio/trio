import contextvars
import functools
import platform
import sys
import threading
import time
import warnings
from contextlib import contextmanager
from math import inf

import attr
import outcome
import sniffio
import pytest
from async_generator import async_generator

from .tutil import check_sequence_matches, gc_collect_harder
from ... import _core
from ..._timeouts import sleep
from ..._util import aiter_compat
from ...testing import (
    wait_all_tasks_blocked,
    Sequencer,
    assert_checkpoints,
)


# slightly different from _timeouts.sleep_forever because it returns the value
# its rescheduled with, which is really only useful for tests of
# rescheduling...
async def sleep_forever():
    return await _core.wait_task_rescheduled(lambda _: _core.Abort.SUCCEEDED)


# Some of our tests need to leak coroutines, and thus trigger the
# "RuntimeWarning: coroutine '...' was never awaited" message. This context
# manager should be used anywhere this happens to hide those messages, because
# (a) when expected they're clutter, (b) on CPython 3.5.x where x < 3, this
# warning can trigger a segfault if we run with warnings turned into errors:
#   https://bugs.python.org/issue27811
@contextmanager
def ignore_coroutine_never_awaited_warnings():
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="coroutine '.*' was never awaited"
        )
        try:
            yield
        finally:
            # Make sure to trigger any coroutine __del__ methods now, before
            # we leave the context manager.
            gc_collect_harder()


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
        await _core.checkpoint()
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


async def test_nursery_warn_use_async_with():
    with pytest.raises(RuntimeError) as excinfo:
        on = _core.open_nursery()
        with on as nursery:
            pass  # pragma: no cover
    excinfo.match(
        r"use 'async with open_nursery\(...\)', not 'with open_nursery\(...\)'"
    )

    # avoid unawaited coro.
    async with on:
        pass


async def test_nursery_main_block_error_basic():
    exc = ValueError("whoops")

    with pytest.raises(ValueError) as excinfo:
        async with _core.open_nursery() as nursery:
            raise exc
    assert excinfo.value is exc


async def test_child_crash_basic():
    exc = ValueError("uh oh")

    async def erroring():
        raise exc

    try:
        # nursery.__aexit__ propagates exception from child back to parent
        async with _core.open_nursery() as nursery:
            nursery.start_soon(erroring)
    except ValueError as e:
        assert e is exc


async def test_basic_interleave():
    async def looper(whoami, record):
        for i in range(3):
            record.append((whoami, i))
            await _core.checkpoint()

    record = []
    async with _core.open_nursery() as nursery:
        nursery.start_soon(looper, "a", record)
        nursery.start_soon(looper, "b", record)

    check_sequence_matches(
        record,
        [{("a", 0), ("b", 0)}, {("a", 1), ("b", 1)}, {("a", 2), ("b", 2)}]
    )


def test_task_crash_propagation():
    looper_record = []

    async def looper():
        try:
            while True:
                await _core.checkpoint()
        except _core.Cancelled:
            print("looper cancelled")
            looper_record.append("cancelled")

    async def crasher():
        raise ValueError("argh")

    async def main():
        async with _core.open_nursery() as nursery:
            nursery.start_soon(looper)
            nursery.start_soon(crasher)

    with pytest.raises(ValueError) as excinfo:
        _core.run(main)

    assert looper_record == ["cancelled"]
    assert excinfo.value.args == ("argh",)


def test_main_and_task_both_crash():
    # If main crashes and there's also a task crash, then we get both in a
    # MultiError
    async def crasher():
        raise ValueError

    async def main():
        async with _core.open_nursery() as nursery:
            crasher_task = nursery.start_soon(crasher)
            raise KeyError

    with pytest.raises(_core.MultiError) as excinfo:
        _core.run(main)
    print(excinfo.value)
    assert set(type(exc)
               for exc in excinfo.value.exceptions) == {ValueError, KeyError}


def test_two_child_crashes():
    async def crasher(etype):
        raise etype

    async def main():
        async with _core.open_nursery() as nursery:
            nursery.start_soon(crasher, KeyError)
            nursery.start_soon(crasher, ValueError)

    with pytest.raises(_core.MultiError) as excinfo:
        _core.run(main)
    assert set(type(exc)
               for exc in excinfo.value.exceptions) == {ValueError, KeyError}


async def test_child_crash_wakes_parent():
    async def crasher():
        raise ValueError

    with pytest.raises(ValueError):
        async with _core.open_nursery() as nursery:
            nursery.start_soon(crasher)
            await sleep_forever()


async def test_reschedule():
    t1 = None
    t2 = None

    async def child1():
        nonlocal t1, t2
        t1 = _core.current_task()
        print("child1 start")
        x = await sleep_forever()
        print("child1 woke")
        assert x == 0
        print("child1 rescheduling t2")
        _core.reschedule(t2, outcome.Error(ValueError()))
        print("child1 exit")

    async def child2():
        nonlocal t1, t2
        print("child2 start")
        t2 = _core.current_task()
        _core.reschedule(t1, outcome.Value(0))
        print("child2 sleep")
        with pytest.raises(ValueError):
            await sleep_forever()
        print("child2 successful exit")

    async with _core.open_nursery() as nursery:
        nursery.start_soon(child1)
        # let t1 run and fall asleep
        await _core.checkpoint()
        nursery.start_soon(child2)


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
    parent_task = _core.current_task()

    async def child():
        assert _core.current_task().parent_nursery.parent_task is parent_task

    async with _core.open_nursery() as nursery:
        nursery.start_soon(child)


async def test_root_task():
    root = _core.current_root_task()
    assert root.parent_nursery is None


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
    assert stats.run_sync_soon_queue_size == 0

    async with _core.open_nursery() as nursery:
        nursery.start_soon(child)
        await wait_all_tasks_blocked()
        token = _core.current_trio_token()
        token.run_sync_soon(lambda: None)
        token.run_sync_soon(lambda: None, idempotent=True)
        stats = _core.current_statistics()
        print(stats)
        # 2 system tasks + us + child
        assert stats.tasks_living == 4
        # the exact value here might shift if we change how we do accounting
        # (currently it only counts tasks that we already know will be
        # runnable on the next pass), but still useful to at least test the
        # difference between now and after we wake up the child:
        assert stats.tasks_runnable == 0
        assert stats.run_sync_soon_queue_size == 2

        nursery.cancel_scope.cancel()
        stats = _core.current_statistics()
        print(stats)
        assert stats.tasks_runnable == 1

    # Give the child a chance to die and the run_sync_soon a chance to clear
    await _core.checkpoint()
    await _core.checkpoint()

    with _core.open_cancel_scope(deadline=_core.current_time() + 5) as scope:
        stats = _core.current_statistics()
        print(stats)
        assert stats.seconds_to_next_deadline == 5
    stats = _core.current_statistics()
    print(stats)
    assert stats.seconds_to_next_deadline == inf


@attr.s(cmp=False, hash=False)
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


def test_instruments(recwarn):
    r1 = TaskRecorder()
    r2 = TaskRecorder()
    r3 = TaskRecorder()

    task = None

    # We use a child task for this, because the main task does some extra
    # bookkeeping stuff that can leak into the instrument results, and we
    # don't want to deal with it.
    async def task_fn():
        nonlocal task
        task = _core.current_task()

        for _ in range(4):
            await _core.checkpoint()
        # replace r2 with r3, to test that we can manipulate them as we go
        _core.remove_instrument(r2)
        with pytest.raises(KeyError):
            _core.remove_instrument(r2)
        # add is idempotent
        _core.add_instrument(r3)
        _core.add_instrument(r3)
        for _ in range(1):
            await _core.checkpoint()

    async def main():
        async with _core.open_nursery() as nursery:
            nursery.start_soon(task_fn)

    _core.run(main, instruments=[r1, r2])

    # It sleeps 5 times, so it runs 6 times
    expected = (
        [("before_run",)] +
        6 * [("schedule", task),
             ("before", task),
             ("after", task)] + [("after_run",)]
    )
    assert len(r1.record) > len(r2.record) > len(r3.record)
    assert r1.record == r2.record + r3.record
    assert list(r1.filter_tasks([task])) == expected


def test_instruments_interleave():
    tasks = {}

    async def two_step1():
        tasks["t1"] = _core.current_task()
        await _core.checkpoint()

    async def two_step2():
        tasks["t2"] = _core.current_task()
        await _core.checkpoint()

    async def main():
        async with _core.open_nursery() as nursery:
            nursery.start_soon(two_step1)
            nursery.start_soon(two_step2)

    r = TaskRecorder()
    _core.run(main, instruments=[r])

    expected = [
        ("before_run",),
        ("schedule", tasks["t1"]),
        ("schedule", tasks["t2"]),
        {
            ("before", tasks["t1"]),
            ("after", tasks["t1"]),
            ("before", tasks["t2"]),
            ("after", tasks["t2"])
        },
        {
            ("schedule", tasks["t1"]),
            ("before", tasks["t1"]),
            ("after", tasks["t1"]),
            ("schedule", tasks["t2"]),
            ("before", tasks["t2"]),
            ("after", tasks["t2"])
        },
        ("after_run",),
    ]  # yapf: disable
    print(list(r.filter_tasks(tasks.values())))
    check_sequence_matches(list(r.filter_tasks(tasks.values())), expected)


def test_null_instrument():
    # undefined instrument methods are skipped
    class NullInstrument:
        pass

    async def main():
        await _core.checkpoint()

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
def test_instruments_crash(caplog):
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
    # And we got a log message
    exc_type, exc_value, exc_traceback = caplog.records[0].exc_info
    assert exc_type is ValueError
    assert str(exc_value) == "oops"
    assert "Instrument has been disabled" in caplog.records[0].message


async def test_cancel_scope_repr():
    # Trivial smoke test
    with _core.open_cancel_scope() as scope:
        assert repr(scope).startswith("<cancel scope object")


def test_cancel_points():
    async def main1():
        with _core.open_cancel_scope() as scope:
            await _core.checkpoint_if_cancelled()
            scope.cancel()
            with pytest.raises(_core.Cancelled):
                await _core.checkpoint_if_cancelled()

    _core.run(main1)

    async def main2():
        with _core.open_cancel_scope() as scope:
            await _core.checkpoint()
            scope.cancel()
            with pytest.raises(_core.Cancelled):
                await _core.checkpoint()

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
            await _core.cancel_shielded_checkpoint()
            await _core.cancel_shielded_checkpoint()
            with pytest.raises(_core.Cancelled):
                await _core.checkpoint()

    _core.run(main4)


async def test_cancel_edge_cases():
    with _core.open_cancel_scope() as scope:
        # Two cancels in a row -- idempotent
        scope.cancel()
        scope.cancel()
        await _core.checkpoint()
    assert scope.cancel_called
    assert scope.cancelled_caught

    with _core.open_cancel_scope() as scope:
        # Check level-triggering
        scope.cancel()
        with pytest.raises(_core.Cancelled):
            await sleep_forever()
        with pytest.raises(_core.Cancelled):
            await sleep_forever()


async def test_cancel_scope_multierror_filtering():
    async def crasher():
        raise KeyError

    try:
        with _core.open_cancel_scope() as outer:
            try:
                async with _core.open_nursery() as nursery:
                    # Two children that get cancelled by the nursery scope
                    nursery.start_soon(sleep_forever)  # t1
                    nursery.start_soon(sleep_forever)  # t2
                    nursery.cancel_scope.cancel()
                    with _core.open_cancel_scope(shield=True):
                        await wait_all_tasks_blocked()
                    # One child that gets cancelled by the outer scope
                    nursery.start_soon(sleep_forever)  # t3
                    outer.cancel()
                    # And one that raises a different error
                    nursery.start_soon(crasher)  # t4
                # and then our __aexit__ also receives an outer Cancelled
            except _core.MultiError as multi_exc:
                # This is outside the nursery scope but inside the outer
                # scope, so the nursery should have absorbed t1 and t2's
                # exceptions but t3 and t4 should remain, plus the Cancelled
                # from 'outer'
                assert len(multi_exc.exceptions) == 3
                summary = {}
                for exc in multi_exc.exceptions:
                    summary.setdefault(type(exc), 0)
                    summary[type(exc)] += 1
                assert summary == {_core.Cancelled: 2, KeyError: 1}
                raise
    except AssertionError:  # pragma: no cover
        raise
    except BaseException as exc:
        # This is ouside the outer scope, so the two outer Cancelled
        # exceptions should have been absorbed, leaving just a regular
        # KeyError from crasher()
        assert type(exc) is KeyError
    else:  # pragma: no cover
        assert False


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
        nursery.start_soon(blocker)
    assert record == ["started"]


async def test_cancel_shielding():
    with _core.open_cancel_scope() as outer:
        with _core.open_cancel_scope() as inner:
            await _core.checkpoint()
            outer.cancel()
            with pytest.raises(_core.Cancelled):
                await _core.checkpoint()

            assert inner.shield is False
            with pytest.raises(TypeError):
                inner.shield = "hello"
            assert inner.shield is False

            inner.shield = True
            assert inner.shield is True
            # shield protects us from 'outer'
            await _core.checkpoint()

            with _core.open_cancel_scope() as innerest:
                innerest.cancel()
                # but it doesn't protect us from scope inside inner
                with pytest.raises(_core.Cancelled):
                    await _core.checkpoint()
            await _core.checkpoint()

            inner.shield = False
            # can disable shield again
            with pytest.raises(_core.Cancelled):
                await _core.checkpoint()

            # re-enable shield
            inner.shield = True
            await _core.checkpoint()
            # shield doesn't protect us from inner itself
            inner.cancel()
            # This should now raise, but be absorbed by the inner scope
            await _core.checkpoint()
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
            nursery.start_soon(leaf, ident + "-l1")
            nursery.start_soon(leaf, ident + "-l2")

    async with _core.open_nursery() as nursery:
        nursery.start_soon(worker, "w1")
        nursery.start_soon(worker, "w2")
        nursery.cancel_scope.cancel()

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

            nursery.start_soon(sleeper)
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
                await wait_all_tasks_blocked()
                assert record == ["sleeping", "cancelled"]


async def test_basic_timeout(mock_clock):
    start = _core.current_time()
    with _core.open_cancel_scope() as scope:
        assert scope.deadline == inf
        scope.deadline = start + 1
        assert scope.deadline == start + 1
    assert not scope.cancel_called
    mock_clock.jump(2)
    await _core.checkpoint()
    await _core.checkpoint()
    await _core.checkpoint()
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
        await _core.checkpoint()
        scope.deadline = start + 10
        await _core.checkpoint()
        mock_clock.jump(5)
        await _core.checkpoint()
        scope.deadline = start + 1
        with pytest.raises(_core.Cancelled):
            await _core.checkpoint()
        with pytest.raises(_core.Cancelled):
            await _core.checkpoint()


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
                await _core.checkpoint()
            with pytest.raises(_core.Cancelled):
                await _core.checkpoint()
            scope2.shield = True
            await _core.checkpoint()
            scope2.cancel()
            with pytest.raises(_core.Cancelled):
                await _core.checkpoint()

    # if a scope is pending, but then gets popped off the stack, then it
    # isn't delivered
    with _core.open_cancel_scope() as scope:
        scope.cancel()
        await _core.cancel_shielded_checkpoint()
    await _core.checkpoint()
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
    stubborn_task = [None]
    stubborn_scope = [None]
    record = []

    async def stubborn_sleeper():
        stubborn_task[0] = _core.current_task()
        with _core.open_cancel_scope() as scope:
            stubborn_scope[0] = scope
            record.append("sleep")
            x = await _core.wait_task_rescheduled(lambda _: _core.Abort.FAILED)
            assert x == 1
            record.append("woke")
            try:
                await _core.checkpoint_if_cancelled()
            except _core.Cancelled:
                record.append("cancelled")

    async with _core.open_nursery() as nursery:
        nursery.start_soon(stubborn_sleeper)
        await wait_all_tasks_blocked()
        assert record == ["sleep"]
        stubborn_scope[0].cancel()
        await wait_all_tasks_blocked()
        # cancel didn't wake it up
        assert record == ["sleep"]
        # wake it up again by hand
        _core.reschedule(stubborn_task[0], outcome.Value(1))
    assert record == ["sleep", "woke", "cancelled"]


def test_broken_abort():
    async def main():
        # These yields are here to work around an annoying warning -- we're
        # going to crash the main loop, and if we (by chance) do this before
        # the run_sync_soon task runs for the first time, then Python gives us
        # a spurious warning about it not being awaited. (I mean, the warning
        # is correct, but here we're testing our ability to deliver a
        # semi-meaningful error after things have gone totally pear-shaped, so
        # it's not relevant.) By letting the run_sync_soon_task run first, we
        # avoid the warning.
        await _core.checkpoint()
        await _core.checkpoint()
        with _core.open_cancel_scope() as scope:
            scope.cancel()
            # None is not a legal return value here
            await _core.wait_task_rescheduled(lambda _: None)

    with pytest.raises(_core.TrioInternalError):
        _core.run(main)

    # Because this crashes, various __del__ methods print complaints on
    # stderr. Make sure that they get run now, so the output is attached to
    # this test.
    gc_collect_harder()


def test_error_in_run_loop():
    # Blow stuff up real good to check we at least get a TrioInternalError
    async def main():
        task = _core.current_task()
        task._schedule_points = "hello!"
        await _core.checkpoint()

    with ignore_coroutine_never_awaited_warnings():
        with pytest.raises(_core.TrioInternalError):
            _core.run(main)


async def test_spawn_system_task():
    record = []

    async def system_task(x):
        record.append(("x", x))
        record.append(("ki", _core.currently_ki_protected()))
        await _core.checkpoint()

    _core.spawn_system_task(system_task, 1)
    await wait_all_tasks_blocked()
    assert record == [("x", 1), ("ki", True)]


# intentionally make a system task crash
def test_system_task_crash():
    async def crasher():
        raise KeyError

    async def main():
        _core.spawn_system_task(crasher)
        await sleep_forever()

    with pytest.raises(_core.TrioInternalError):
        _core.run(main)


def test_system_task_crash_MultiError():
    async def crasher1():
        raise KeyError

    async def crasher2():
        raise ValueError

    async def system_task():
        async with _core.open_nursery() as nursery:
            nursery.start_soon(crasher1)
            nursery.start_soon(crasher2)

    async def main():
        _core.spawn_system_task(system_task)
        await sleep_forever()

    with pytest.raises(_core.MultiError) as excinfo:
        _core.run(main)

    assert len(excinfo.value.exceptions) == 2
    cause_types = set()
    for exc in excinfo.value.exceptions:
        assert type(exc) is _core.TrioInternalError
        cause_types.add(type(exc.__cause__))
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
            nursery.start_soon(crasher)
            nursery.start_soon(cancelme)

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


# This used to fail because checkpoint was a yield followed by an immediate
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
        await _core.checkpoint()
        with pytest.raises(_core.Cancelled):
            mock_clock.jump(10)
            await _core.checkpoint()


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
        nursery.start_soon(child1)
        nursery.start_soon(child2)

    assert record == [
        "child1 raise", "child1 sleep", "child2 wake", "child2 sleep again",
        "child1 re-raise", "child1 success", "child2 re-raise",
        "child2 success"
    ]


# At least as of CPython 3.6, using .throw() to raise an exception inside a
# coroutine/generator causes the original exc_info state to be lost, so things
# like re-raising and exception chaining are broken.
#
# https://bugs.python.org/issue29587
async def test_exc_info_after_yield_error():
    child_task = None

    async def child():
        nonlocal child_task
        child_task = _core.current_task()

        try:
            raise KeyError
        except Exception:
            try:
                await sleep_forever()
            except Exception:
                pass
            raise

    with pytest.raises(KeyError):
        async with _core.open_nursery() as nursery:
            nursery.start_soon(child)
            await wait_all_tasks_blocked()
            _core.reschedule(child_task, outcome.Error(ValueError()))


# Similar to previous test -- if the ValueError() gets sent in via 'throw',
# then Python's normal implicit chaining stuff is broken.
async def test_exception_chaining_after_yield_error():
    child_task = None

    async def child():
        nonlocal child_task
        child_task = _core.current_task()

        try:
            raise KeyError
        except Exception:
            await sleep_forever()

    with pytest.raises(ValueError) as excinfo:
        async with _core.open_nursery() as nursery:
            nursery.start_soon(child)
            await wait_all_tasks_blocked()
            _core.reschedule(child_task, outcome.Error(ValueError()))

    assert isinstance(excinfo.value.__context__, KeyError)


async def test_nursery_exception_chaining_doesnt_make_context_loops():
    async def crasher():
        raise KeyError

    with pytest.raises(_core.MultiError) as excinfo:
        async with _core.open_nursery() as nursery:
            nursery.start_soon(crasher)
            raise ValueError
    assert excinfo.value.__context__ is None


def test_TrioToken_identity():
    async def get_and_check_token():
        token = _core.current_trio_token()
        # Two calls in the same run give the same object
        assert token is _core.current_trio_token()
        return token

    t1 = _core.run(get_and_check_token)
    t2 = _core.run(get_and_check_token)
    assert t1 is not t2
    assert t1 != t2
    assert hash(t1) != hash(t2)


async def test_TrioToken_run_sync_soon_basic():
    record = []

    def cb(x):
        record.append(("cb", x))

    token = _core.current_trio_token()
    token.run_sync_soon(cb, 1)
    assert not record
    await wait_all_tasks_blocked()
    assert record == [("cb", 1)]


def test_TrioToken_run_sync_soon_too_late():
    token = None

    async def main():
        nonlocal token
        token = _core.current_trio_token()

    _core.run(main)
    assert token is not None
    with pytest.raises(_core.RunFinishedError):
        token.run_sync_soon(lambda: None)  # pragma: no branch


async def test_TrioToken_run_sync_soon_idempotent():
    record = []

    def cb(x):
        record.append(x)

    token = _core.current_trio_token()
    token.run_sync_soon(cb, 1)
    token.run_sync_soon(cb, 1, idempotent=True)
    token.run_sync_soon(cb, 1, idempotent=True)
    token.run_sync_soon(cb, 1, idempotent=True)
    token.run_sync_soon(cb, 2, idempotent=True)
    token.run_sync_soon(cb, 2, idempotent=True)
    await wait_all_tasks_blocked()
    assert len(record) == 3
    assert sorted(record) == [1, 1, 2]

    # ordering test
    record = []
    for _ in range(3):
        for i in range(100):
            token.run_sync_soon(cb, i, idempotent=True)
    await wait_all_tasks_blocked()
    if (
        sys.version_info < (3, 6)
        and platform.python_implementation() == "CPython"
    ):
        # no order guarantees
        record.sort()
    # Otherwise, we guarantee FIFO
    assert record == list(range(100))


def test_TrioToken_run_sync_soon_idempotent_requeue():
    # We guarantee that if a call has finished, queueing it again will call it
    # again. Due to the lack of synchronization, this effectively means that
    # we have to guarantee that once a call has *started*, queueing it again
    # will call it again. Also this is much easier to test :-)
    record = []

    def redo(token):
        record.append(None)
        try:
            token.run_sync_soon(redo, token, idempotent=True)
        except _core.RunFinishedError:
            pass

    async def main():
        token = _core.current_trio_token()
        token.run_sync_soon(redo, token, idempotent=True)
        await _core.checkpoint()
        await _core.checkpoint()
        await _core.checkpoint()

    _core.run(main)

    assert len(record) >= 2


def test_TrioToken_run_sync_soon_after_main_crash():
    record = []

    async def main():
        token = _core.current_trio_token()
        # After main exits but before finally cleaning up, callback processed
        # normally
        token.run_sync_soon(lambda: record.append("sync-cb"))
        raise ValueError

    with pytest.raises(ValueError):
        _core.run(main)

    assert record == ["sync-cb"]


def test_TrioToken_run_sync_soon_crashes():
    record = set()

    async def main():
        token = _core.current_trio_token()
        token.run_sync_soon(lambda: dict()["nope"])
        # check that a crashing run_sync_soon callback doesn't stop further
        # calls to run_sync_soon
        token.run_sync_soon(lambda: record.add("2nd run_sync_soon ran"))
        try:
            await sleep_forever()
        except _core.Cancelled:
            record.add("cancelled!")

    with pytest.raises(_core.TrioInternalError) as excinfo:
        _core.run(main)

    assert type(excinfo.value.__cause__) is KeyError
    assert record == {"2nd run_sync_soon ran", "cancelled!"}


async def test_TrioToken_run_sync_soon_FIFO():
    N = 100
    record = []
    token = _core.current_trio_token()
    for i in range(N):
        token.run_sync_soon(lambda j: record.append(j), i)
    await wait_all_tasks_blocked()
    assert record == list(range(N))


def test_TrioToken_run_sync_soon_starvation_resistance():
    # Even if we push callbacks in from callbacks, so that the callback queue
    # never empties out, then we still can't starve out other tasks from
    # running.
    token = None
    record = []

    def naughty_cb(i):
        nonlocal token
        try:
            token.run_sync_soon(naughty_cb, i + 1)
        except _core.RunFinishedError:
            record.append(("run finished", i))

    async def main():
        nonlocal token
        token = _core.current_trio_token()
        token.run_sync_soon(naughty_cb, 0)
        record.append("starting")
        for _ in range(20):
            await _core.checkpoint()

    _core.run(main)
    assert len(record) == 2
    assert record[0] == "starting"
    assert record[1][0] == "run finished"
    assert record[1][1] >= 20


def test_TrioToken_run_sync_soon_threaded_stress_test():
    cb_counter = 0

    def cb():
        nonlocal cb_counter
        cb_counter += 1

    def stress_thread(token):
        try:
            while True:
                token.run_sync_soon(cb)
                time.sleep(0)
        except _core.RunFinishedError:
            pass

    async def main():
        token = _core.current_trio_token()
        thread = threading.Thread(target=stress_thread, args=(token,))
        thread.start()
        for _ in range(10):
            start_value = cb_counter
            while cb_counter == start_value:
                await sleep(0.01)

    _core.run(main)
    print(cb_counter)


async def test_TrioToken_run_sync_soon_massive_queue():
    # There are edge cases in the wakeup fd code when the wakeup fd overflows,
    # so let's try to make that happen. This is also just a good stress test
    # in general. (With the current-as-of-2017-02-14 code using a socketpair
    # with minimal buffer, Linux takes 6 wakeups to fill the buffer and macOS
    # takes 1 wakeup. So 1000 is overkill if anything. Windows OTOH takes
    # ~600,000 wakeups, but has the same code paths...)
    COUNT = 1000
    token = _core.current_trio_token()
    counter = [0]

    def cb(i):
        # This also tests FIFO ordering of callbacks
        assert counter[0] == i
        counter[0] += 1

    for i in range(COUNT):
        token.run_sync_soon(cb, i)
    await wait_all_tasks_blocked()
    assert counter[0] == COUNT


async def test_slow_abort_basic():
    with _core.open_cancel_scope() as scope:
        scope.cancel()
        with pytest.raises(_core.Cancelled):
            task = _core.current_task()
            token = _core.current_trio_token()

            def slow_abort(raise_cancel):
                result = outcome.capture(raise_cancel)
                token.run_sync_soon(_core.reschedule, task, result)
                return _core.Abort.FAILED

            await _core.wait_task_rescheduled(slow_abort)


async def test_slow_abort_edge_cases():
    record = []

    async def slow_aborter():
        task = _core.current_task()
        token = _core.current_trio_token()

        def slow_abort(raise_cancel):
            record.append("abort-called")
            result = outcome.capture(raise_cancel)
            token.run_sync_soon(_core.reschedule, task, result)
            return _core.Abort.FAILED

        with pytest.raises(_core.Cancelled):
            record.append("sleeping")
            await _core.wait_task_rescheduled(slow_abort)
        record.append("cancelled")
        # blocking again, this time it's okay, because we're shielded
        await _core.checkpoint()
        record.append("done")

    with _core.open_cancel_scope() as outer1:
        with _core.open_cancel_scope() as outer2:
            async with _core.open_nursery() as nursery:
                # So we have a task blocked on an operation that can't be
                # aborted immediately
                nursery.start_soon(slow_aborter)
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


async def test_task_tree_introspection():
    tasks = {}
    nurseries = {}

    async def parent():
        tasks["parent"] = _core.current_task()

        assert tasks["parent"].child_nurseries == []

        async with _core.open_nursery() as nursery1:
            async with _core.open_nursery() as nursery2:
                assert tasks["parent"].child_nurseries == [nursery1, nursery2]

        assert tasks["parent"].child_nurseries == []

        async with _core.open_nursery() as nursery:
            nurseries["parent"] = nursery
            nursery.start_soon(child1)

        # Upward links survive after tasks/nurseries exit
        assert nurseries["parent"].parent_task is tasks["parent"]
        assert tasks["child1"].parent_nursery is nurseries["parent"]
        assert nurseries["child1"].parent_task is tasks["child1"]
        assert tasks["child2"].parent_nursery is nurseries["child1"]

        nursery = _core.current_task().parent_nursery
        # Make sure that chaining eventually gives a nursery of None (and not,
        # for example, an error)
        while nursery is not None:
            t = nursery.parent_task
            nursery = t.parent_nursery

    async def child2():
        tasks["child2"] = _core.current_task()
        assert tasks["parent"].child_nurseries == [nurseries["parent"]]
        assert nurseries["parent"].child_tasks == frozenset({tasks["child1"]})
        assert tasks["child1"].child_nurseries == [nurseries["child1"]]
        assert nurseries["child1"].child_tasks == frozenset({tasks["child2"]})
        assert tasks["child2"].child_nurseries == []

    async def child1():
        tasks["child1"] = _core.current_task()
        async with _core.open_nursery() as nursery:
            nurseries["child1"] = nursery
            nursery.start_soon(child2)

    async with _core.open_nursery() as nursery:
        nursery.start_soon(parent)


async def test_nursery_closure():
    async def child1(nursery):
        # We can add new tasks to the nursery even after entering __aexit__,
        # so long as there are still tasks running
        nursery.start_soon(child2)

    async def child2():
        pass

    async with _core.open_nursery() as nursery:
        nursery.start_soon(child1, nursery)

    # But once we've left __aexit__, the nursery is closed
    with pytest.raises(RuntimeError):
        nursery.start_soon(child2)


async def test_spawn_name():
    async def func1(expected):
        task = _core.current_task()
        assert expected in task.name

    async def func2():  # pragma: no cover
        pass

    async with _core.open_nursery() as nursery:
        for spawn_fn in [nursery.start_soon, _core.spawn_system_task]:
            spawn_fn(func1, "func1")
            spawn_fn(func1, "func2", name=func2)
            spawn_fn(func1, "func3", name="func3")
            spawn_fn(functools.partial(func1, "func1"))
            spawn_fn(func1, "object", name=object())


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


def test_nice_error_on_bad_calls_to_run_or_spawn():
    def bad_call_run(*args):
        _core.run(*args)

    def bad_call_spawn(*args):
        async def main():
            async with _core.open_nursery() as nursery:
                nursery.start_soon(*args)

        _core.run(main)

    class Deferred:
        "Just kidding"

    with ignore_coroutine_never_awaited_warnings():
        for bad_call in bad_call_run, bad_call_spawn:

            async def f():  # pragma: no cover
                pass

            with pytest.raises(TypeError) as excinfo:
                bad_call(f())
            assert "expecting an async function" in str(excinfo.value)

            import asyncio

            @asyncio.coroutine
            def generator_based_coro():  # pragma: no cover
                yield from asyncio.sleep(1)

            with pytest.raises(TypeError) as excinfo:
                bad_call(generator_based_coro())
            assert "asyncio" in str(excinfo.value)

            with pytest.raises(TypeError) as excinfo:
                bad_call(asyncio.Future())
            assert "asyncio" in str(excinfo.value)

            with pytest.raises(TypeError) as excinfo:
                bad_call(generator_based_coro)
            assert "asyncio" in str(excinfo.value)

            with pytest.raises(TypeError) as excinfo:
                bad_call(lambda: asyncio.Future())
            assert "asyncio" in str(excinfo.value)

            with pytest.raises(TypeError) as excinfo:
                bad_call(Deferred())
            assert "twisted" in str(excinfo.value)

            with pytest.raises(TypeError) as excinfo:
                bad_call(lambda: Deferred())
            assert "twisted" in str(excinfo.value)

            with pytest.raises(TypeError) as excinfo:
                bad_call(len, [1, 2, 3])
            assert "appears to be synchronous" in str(excinfo.value)

            @async_generator
            async def async_gen(arg):  # pragma: no cover
                pass

            with pytest.raises(TypeError) as excinfo:
                bad_call(async_gen, 0)
            msg = "expected an async function but got an async generator"
            assert msg in str(excinfo.value)

            # Make sure no references are kept around to keep anything alive
            del excinfo


def test_calling_asyncio_function_gives_nice_error():
    async def misguided():
        import asyncio
        await asyncio.sleep(1)

    with pytest.raises(TypeError) as excinfo:
        _core.run(misguided)

    assert "asyncio" in str(excinfo.value)


async def test_trivial_yields():
    with assert_checkpoints():
        await _core.checkpoint()

    with assert_checkpoints():
        await _core.checkpoint_if_cancelled()
        await _core.cancel_shielded_checkpoint()

    with assert_checkpoints():
        async with _core.open_nursery():
            pass

    with _core.open_cancel_scope() as cancel_scope:
        cancel_scope.cancel()
        with pytest.raises(_core.MultiError) as excinfo:
            async with _core.open_nursery():
                raise KeyError
        assert len(excinfo.value.exceptions) == 2
        assert set(type(e) for e in excinfo.value.exceptions) == {
            KeyError, _core.Cancelled
        }


async def test_nursery_start(autojump_clock):
    async def no_args():  # pragma: no cover
        pass

    # Errors in calling convention get raised immediately from start
    async with _core.open_nursery() as nursery:
        with pytest.raises(TypeError):
            await nursery.start(no_args)

    async def sleep_then_start(
        seconds, *, task_status=_core.TASK_STATUS_IGNORED
    ):
        repr(task_status)  # smoke test
        await sleep(seconds)
        task_status.started(seconds)
        await sleep(seconds)

    # Basic happy-path check: start waits for the task to call started(), then
    # returns, passes back the value, and the given nursery then waits for it
    # to exit.
    for seconds in [1, 2]:
        async with _core.open_nursery() as nursery:
            assert len(nursery.child_tasks) == 0
            t0 = _core.current_time()
            assert await nursery.start(sleep_then_start, seconds) == seconds
            assert _core.current_time() - t0 == seconds
            assert len(nursery.child_tasks) == 1
        assert _core.current_time() - t0 == 2 * seconds

    # Make sure TASK_STATUS_IGNORED works so task function can be called
    # directly
    t0 = _core.current_time()
    await sleep_then_start(3)
    assert _core.current_time() - t0 == 2 * 3

    # calling started twice
    async def double_started(task_status=_core.TASK_STATUS_IGNORED):
        task_status.started()
        with pytest.raises(RuntimeError):
            task_status.started()

    async with _core.open_nursery() as nursery:
        await nursery.start(double_started)

    # child crashes before calling started -> error comes out of .start()
    async def raise_keyerror(task_status=_core.TASK_STATUS_IGNORED):
        raise KeyError("oops")

    async with _core.open_nursery() as nursery:
        with pytest.raises(KeyError):
            await nursery.start(raise_keyerror)

    # child exiting cleanly before calling started -> triggers a RuntimeError
    async def nothing(task_status=_core.TASK_STATUS_IGNORED):
        return

    async with _core.open_nursery() as nursery:
        with pytest.raises(RuntimeError) as excinfo:
            await nursery.start(nothing)
        assert "exited without calling" in str(excinfo.value)

    # if the call to start() is cancelled, then the call to started() does
    # nothing -- the child keeps executing under start(). The value it passed
    # is ignored; start() raises Cancelled.
    async def just_started(task_status=_core.TASK_STATUS_IGNORED):
        task_status.started("hi")

    async with _core.open_nursery() as nursery:
        with _core.open_cancel_scope() as cs:
            cs.cancel()
            with pytest.raises(_core.Cancelled):
                await nursery.start(just_started)

    # and if after the no-op started(), the child crashes, the error comes out
    # of start()
    async def raise_keyerror_after_started(
        task_status=_core.TASK_STATUS_IGNORED
    ):
        task_status.started()
        raise KeyError("whoopsiedaisy")

    async with _core.open_nursery() as nursery:
        with _core.open_cancel_scope() as cs:
            cs.cancel()
            with pytest.raises(_core.MultiError) as excinfo:
                await nursery.start(raise_keyerror_after_started)
    assert set(type(e) for e in excinfo.value.exceptions) == {
        _core.Cancelled, KeyError
    }

    # trying to start in a closed nursery raises an error immediately
    async with _core.open_nursery() as closed_nursery:
        pass
    t0 = _core.current_time()
    with pytest.raises(RuntimeError):
        await closed_nursery.start(sleep_then_start, 7)
    assert _core.current_time() == t0


async def test_task_nursery_stack():
    task = _core.current_task()
    assert task._child_nurseries == []
    async with _core.open_nursery() as nursery1:
        assert task._child_nurseries == [nursery1]
        with pytest.raises(KeyError):
            async with _core.open_nursery() as nursery2:
                assert task._child_nurseries == [nursery1, nursery2]
                raise KeyError
        assert task._child_nurseries == [nursery1]
    assert task._child_nurseries == []


async def test_nursery_start_with_cancelled_nursery():
    # This function isn't testing task_status, it's using task_status as a
    # convenient way to get a nursery that we can test spawning stuff into.
    async def setup_nursery(task_status=_core.TASK_STATUS_IGNORED):
        async with _core.open_nursery() as nursery:
            task_status.started(nursery)
            await sleep_forever()

    # Calls started() while children are asleep, so we can make sure
    # that the cancellation machinery notices and aborts when a sleeping task
    # is moved into a cancelled scope.
    async def sleeping_children(fn, *, task_status=_core.TASK_STATUS_IGNORED):
        async with _core.open_nursery() as nursery:
            nursery.start_soon(sleep_forever)
            nursery.start_soon(sleep_forever)
            await wait_all_tasks_blocked()
            fn()
            task_status.started()

    # Cancelling the setup_nursery just *before* calling started()
    async with _core.open_nursery() as nursery:
        target_nursery = await nursery.start(setup_nursery)
        await target_nursery.start(
            sleeping_children, target_nursery.cancel_scope.cancel
        )

    # Cancelling the setup_nursery just *after* calling started()
    async with _core.open_nursery() as nursery:
        target_nursery = await nursery.start(setup_nursery)
        await target_nursery.start(sleeping_children, lambda: None)
        target_nursery.cancel_scope.cancel()


async def test_nursery_start_keeps_nursery_open(autojump_clock):
    async def sleep_a_bit(task_status=_core.TASK_STATUS_IGNORED):
        await sleep(2)
        task_status.started()
        await sleep(3)

    async with _core.open_nursery() as nursery1:
        t0 = _core.current_time()
        async with _core.open_nursery() as nursery2:
            # Start the 'start' call running in the background
            nursery1.start_soon(nursery2.start, sleep_a_bit)
            # Sleep a bit
            await sleep(1)
            # Start another one.
            nursery1.start_soon(nursery2.start, sleep_a_bit)
            # Then exit this nursery. At this point, there are no tasks
            # present in this nursery -- the only thing keeping it open is
            # that the tasks will be placed into it soon, when they call
            # started().
        assert _core.current_time() - t0 == 6

    # Check that it still works even if the task that the nursery is waiting
    # for ends up crashing, and never actually enters the nursery.
    async def sleep_then_crash(task_status=_core.TASK_STATUS_IGNORED):
        await sleep(7)
        raise KeyError

    async def start_sleep_then_crash(nursery):
        with pytest.raises(KeyError):
            await nursery.start(sleep_then_crash)

    async with _core.open_nursery() as nursery1:
        t0 = _core.current_time()
        async with _core.open_nursery() as nursery2:
            nursery1.start_soon(start_sleep_then_crash, nursery2)
            await wait_all_tasks_blocked()
        assert _core.current_time() - t0 == 7


async def test_nursery_explicit_exception():
    with pytest.raises(KeyError):
        async with _core.open_nursery():
            raise KeyError()


async def test_nursery_stop_iteration():
    async def fail():
        raise ValueError

    try:
        async with _core.open_nursery() as nursery:
            nursery.start_soon(fail)
            raise StopIteration
    except _core.MultiError as e:
        assert tuple(map(type, e.exceptions)) == (StopIteration, ValueError)


async def test_nursery_stop_async_iteration():
    class it(object):
        def __init__(self, count):
            self.count = count
            self.val = 0

        async def __anext__(self):
            await sleep(0)
            val = self.val
            if val >= self.count:
                raise StopAsyncIteration
            self.val += 1
            return val

    class async_zip(object):
        def __init__(self, *largs):
            self.nexts = [obj.__anext__ for obj in largs]

        async def _accumulate(self, f, items, i):
            items[i] = await f()

        @aiter_compat
        def __aiter__(self):
            return self

        async def __anext__(self):
            nexts = self.nexts
            items = [
                None,
            ] * len(nexts)
            got_stop = False

            def handle(exc):
                nonlocal got_stop
                got_stop = True
                return None

            with _core.MultiError.catch(StopAsyncIteration, handle):
                async with _core.open_nursery() as nursery:
                    for i, f in enumerate(nexts):
                        nursery.start_soon(self._accumulate, f, items, i)

            if got_stop:
                raise StopAsyncIteration
            return items

    result = []
    async for vals in async_zip(it(4), it(2)):
        result.append(vals)
    assert result == [[0, 0], [1, 1]]


def test_contextvar_support():
    var = contextvars.ContextVar("test")
    var.set("before")

    assert var.get() == "before"

    async def inner():
        task = _core.current_task()
        assert task.context.get(var) == "before"
        assert var.get() == "before"
        var.set("after")
        assert var.get() == "after"
        assert var in task.context
        assert task.context.get(var) == "after"

    _core.run(inner)
    assert var.get() == "before"


async def test_contextvar_multitask():
    var = contextvars.ContextVar("test", default="hmmm")

    async def t1():
        assert var.get() == "hmmm"
        var.set("hmmmm")
        assert var.get() == "hmmmm"

    async def t2():
        assert var.get() == "hmmmm"

    async with _core.open_nursery() as n:
        n.start_soon(t1)
        await wait_all_tasks_blocked()
        assert var.get() == "hmmm"
        var.set("hmmmm")
        n.start_soon(t2)
        await wait_all_tasks_blocked()


def test_system_task_contexts():
    cvar = contextvars.ContextVar('qwilfish')
    cvar.set("water")

    async def system_task():
        assert cvar.get() == "water"

    async def regular_task():
        assert cvar.get() == "poison"

    async def inner():
        async with _core.open_nursery() as nursery:
            cvar.set("poison")
            nursery.start_soon(regular_task)
            _core.spawn_system_task(system_task)
            await wait_all_tasks_blocked()

    _core.run(inner)


def test_Cancelled_init():
    check_Cancelled_error = pytest.raises(
        RuntimeError, match='should not be raised directly'
    )

    with check_Cancelled_error:
        raise _core.Cancelled

    with check_Cancelled_error:
        _core.Cancelled()

    # private constructor should not raise
    _core.Cancelled._init()


def test_sniffio_integration():
    with pytest.raises(sniffio.AsyncLibraryNotFoundError):
        sniffio.current_async_library()

    async def check_inside_trio():
        assert sniffio.current_async_library() == "trio"

    _core.run(check_inside_trio)

    with pytest.raises(sniffio.AsyncLibraryNotFoundError):
        sniffio.current_async_library()


async def test_Task_custom_sleep_data():
    task = _core.current_task()
    assert task.custom_sleep_data is None
    task.custom_sleep_data = 1
    assert task.custom_sleep_data == 1
    await _core.checkpoint()
    assert task.custom_sleep_data is None
