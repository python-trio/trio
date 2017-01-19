import threading
import sys
import time
import pytest
import attr

from .test_util import check_sequence_matches, check_exc_chain
from ...testing import busy_wait_for, quiesce

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


async def test_basic_spawn_join():
    async def child(x):
        return 2 * x
    task = await _core.spawn(child, 10)
    assert (await task.join()).unwrap() == 20


async def test_join_crash():
    exc = ValueError("uh oh")
    async def erroring():
        raise exc

    task = await _core.spawn(erroring)
    result = await task.join()
    assert result.error is exc


async def test_join_nowait():
    async def child():
        return 1
    task = await _core.spawn(child)
    with pytest.raises(_core.WouldBlock):
        task.join_nowait()
    await task.join()
    assert task.join_nowait().unwrap() == 1


async def test_basic_interleave():
    async def looper(whoami, record):
        for i in range(3):
            record.append((whoami, i))
            await _core.yield_briefly()

    record = []
    t1 = await _core.spawn(looper, "a", record)
    t2 = await _core.spawn(looper, "b", record)
    await t1.join()
    await t2.join()

    check_sequence_matches(record, [
        {("a", 0), ("b", 0)},
        {("a", 1), ("b", 1)},
        {("a", 2), ("b", 2)}])


def test_task_crash():
    looper_record = []
    async def looper():
        try:
            while True:
                await _core.yield_briefly()
        except _core.Cancelled:
            looper_record.append("cancelled")

    async def crasher():
        raise ValueError("argh")

    main_record = []
    async def main():
        try:
            await _core.spawn(looper)
            await _core.spawn(crasher)
            while True:
                await _core.yield_briefly()
        except _core.Cancelled:
            main_record.append("cancelled")

    with pytest.raises(_core.UnhandledExceptionError) as excinfo:
        _core.run(main)

    assert looper_record == ["cancelled"]
    assert main_record == ["cancelled"]
    assert type(excinfo.value) is _core.UnhandledExceptionError
    assert type(excinfo.value.__cause__) is ValueError
    assert excinfo.value.__cause__.args == ("argh",)


def test_crash_beats_main_task():
    # If main crashes and there's also a task crash, then we always finish
    # with an UnhandledExceptionError, no matter what order the two events are
    # observed in.
    async def crasher():
        raise ValueError

    async def main(wait, crash):
        await _core.spawn(crasher)
        if wait:
            await _core.yield_briefly()
        if error:
            raise KeyError
        else:
            return "hi"

    for wait in [True, False]:
        for error in [True, False]:
            with pytest.raises(_core.UnhandledExceptionError) as excinfo:
                _core.run(main, wait, error)
            assert type(excinfo.value.__cause__) is ValueError
            if error:
                assert type(excinfo.value.__cause__.__context__) is KeyError
            else:
                assert excinfo.value.__cause__.__context__ is None


# multiple crashes get chained, with the last one on top
def test_two_crashes():
    async def crasher(etype):
        raise etype

    async def main():
        await _core.spawn(crasher, KeyError)
        try:
            while True:
                await _core.yield_briefly()
        finally:
            await _core.spawn(crasher, ValueError)

    with pytest.raises(_core.UnhandledExceptionError) as excinfo:
        _core.run(main)
    check_exc_chain(excinfo.value, [
        # second crasher
        _core.UnhandledExceptionError, "cause", ValueError,
        # first crasher
        "context", _core.UnhandledExceptionError, "cause", KeyError,
        # result of main
        "context", _core.TaskCancelled,
    ])


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

    t1 = await _core.spawn(child1)
    # let t1 run and fall asleep
    await _core.yield_briefly()
    t2 = await _core.spawn(child2)
    (await t2.join()).unwrap()


async def test_notify_queues():
    async def child():
        return 1

    q1 = _core.Queue(1)
    q2 = _core.Queue(1)
    q3 = _core.Queue(1)
    q4 = _core.Queue(1)
    task = await _core.spawn(child, notify_queues=[q1, q2])
    task.add_notify_queue(q3)

    # okay to discard one that was never there
    task.discard_notify_queue(q4)

    # discard one that *was* there, to make sure it works
    task.discard_notify_queue(q2)

    # add one that's already there:
    with pytest.raises(ValueError):
        task.add_notify_queue(q1)
    with pytest.raises(ValueError):
        task.add_notify_queue(q3)

    # q1 and q3 should be there now, check that they indeed get notified
    await _core.yield_briefly()
    await _core.yield_briefly()
    await _core.yield_briefly()
    assert task.join_nowait().unwrap() == 1
    assert q1.get_nowait() is task
    with pytest.raises(_core.WouldBlock):
        q2.get_nowait()
    assert q3.get_nowait() is task
    with pytest.raises(_core.WouldBlock):
        q4.get_nowait()

    # can re-add the queue now
    for _ in range(2):
        assert q1.empty()
        task.add_notify_queue(q1)
        # and it immediately receives the result:
        assert q1.get_nowait() is task
        assert q1.empty()
        # and since it was used, it's already gone from the set, so we can
        # loop around and do it again


def test_broken_notify_queue():
    class BadQueue:
        def put_nowait(self, obj):
            raise KeyError

    async def child():
        return 1
    async def main1():
        await _core.spawn(child, notify_queues=[BadQueue()])
        while True:
            await _core.yield_briefly()
    with pytest.raises(_core.UnhandledExceptionError) as excinfo:
        _core.run(main1)
    assert "error notifying task watcher" in str(excinfo.value)
    check_exc_chain(excinfo.value, [
        _core.UnhandledExceptionError, "cause", KeyError,
        "context", _core.TaskCancelled,
    ])

    # add_notify_queue with broken queue after exit
    async def main2():
        task = await _core.spawn(child)
        result = await task.join()
        assert result.unwrap() == 1
        # This raises immediately, rather than crashing the run.
        # There's an argument for doing it either way, but this way we keep
        # the error closer to the offending code.
        with pytest.raises(KeyError):
            task.add_notify_queue(BadQueue())
    _core.run(main2)

    # BadQueue doesn't count as a successful notification, so if we were
    # trying to notify of a crash, then we get two rounds of
    # UnhandledExceptionError:
    async def crasher():
        raise ValueError
    async def main3():
        task = await _core.spawn(crasher, notify_queues=[BadQueue()])
    with pytest.raises(_core.UnhandledExceptionError) as excinfo:
        _core.run(main3)
    check_exc_chain(excinfo.value, [
        _core.UnhandledExceptionError, "cause", ValueError,
        "context", _core.UnhandledExceptionError, "cause", KeyError,
    ])


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

    child_task = await _core.spawn(child)
    assert child_task == (await child_task.join()).unwrap()


@attr.s(slots=True, cmp=False, hash=False)
class Recorder(_core.Instrument):
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
    r1 = Recorder()
    r2 = Recorder()
    r3 = Recorder()

    async def main():
        for _ in range(2):
            await _core.yield_briefly()
        cp = _core.current_instruments()
        assert cp == [r1, r2]
        # replace r2 with r3, to test that we can manipulate them as we go
        cp[1] = r3
        for _ in range(1):
            await _core.yield_briefly()
        return _core.current_task()
    task = _core.run(main, instruments=[r1, r2])
    # It sleeps 3 times, so it runs 4 times
    expected = [("schedule", task), ("before", task), ("after", task),
                ("schedule", task), ("before", task), ("after", task),
                ("schedule", task), ("before", task), ("after", task),
                ("schedule", task), ("before", task), ("after", task),
                ("close",)]
    assert len(r1.record) > len(r2.record) > len(r3.record)
    assert r1.record == r2.record + r3.record
    # Need to filter b/c there's also the system task bumping around in the
    # record:
    assert list(r1.filter_tasks([task])) == expected

    # since we didn't use call_soon, the system task should have only
    # scheduled twice (once at the beginning to set up, and once at the end
    # when cancelled). this caught a subtle bug in the first version of the
    # code where it was running on every cycle...:
    assert len(r1.record) == len(expected) + 6


def test_instruments_interleave():
    tasks = {}

    async def two_step1():
        await _core.yield_briefly()
    async def two_step2():
        await _core.yield_briefly()

    async def main():
        tasks["main"] = _core.current_task()
        tasks["t1"] = await _core.spawn(two_step1)
        tasks["t2"] = await _core.spawn(two_step2)

    # pass in a base class Instrument just to check that its null methods are
    # spelled right
    base = _core.Instrument()
    r = Recorder()
    _core.run(main, instruments=[base, r])

    expected = [
        ("schedule", tasks["main"]),
        ("before", tasks["main"]),
        ("schedule", tasks["t1"]),
        ("schedule", tasks["t2"]),
        ("after", tasks["main"]),
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
    check_sequence_matches(list(r.filter_tasks(tasks.values())), expected)


def test_cancel_points():
    async def main1():
        _core.cancellation_point_no_yield()
        _core.current_task().cancel_nowait()
        with pytest.raises(_core.TaskCancelled):
            _core.cancellation_point_no_yield()
    _core.run(main1)

    async def main2():
        _core.current_task().cancel_nowait()
        with pytest.raises(_core.TaskCancelled):
            await _core.yield_briefly()
    _core.run(main2)

    async def main3():
        _core.current_task().cancel_nowait()
        with pytest.raises(_core.TaskCancelled):
            await sleep_forever()
    _core.run(main3)

    async def main4():
        _core.current_task().cancel_nowait()
        await _core.yield_briefly_no_cancel()
        await _core.yield_briefly_no_cancel()
        with pytest.raises(_core.TaskCancelled):
            await _core.yield_briefly()
    _core.run(main4)

async def test_cancel_edge_cases():
    async def child():
        await _core.yield_briefly()

    t1 = await _core.spawn(child)
    t1.cancel_nowait()
    # Can't cancel a task that was already cancelled
    with pytest.raises(RuntimeError) as excinfo:
        t1.cancel_nowait()
    assert "already canceled" in str(excinfo.value)
    result = await t1.join()
    assert type(result.error) is _core.TaskCancelled

    t2 = await _core.spawn(child)
    await t2.join()
    # Can't cancel a task that has already exited
    with pytest.raises(RuntimeError) as excinfo:
        t2.cancel_nowait()
    assert "already exited" in str(excinfo.value)


async def test_cancel_custom_exc():
    class MyCancelled(_core.Cancelled):
        pass

    async def child():
        with pytest.raises(MyCancelled):
            await sleep_forever()
        return "ok"

    task = await _core.spawn(child)
    with pytest.raises(TypeError):
        # exception type rather than exception instance
        task.cancel_nowait(MyCancelled)
    with pytest.raises(TypeError):
        # other exception types not allowed
        task.cancel_nowait(ValueError())
    task.cancel_nowait(MyCancelled())
    result = await task.join()
    assert result.unwrap() == "ok"


async def test_basic_timeout(mock_clock):
    start = _core.current_time()
    with _core.move_on_at(start + 1) as timeout:
        assert timeout.deadline == _core.current_deadline() == start + 1
        timeout.deadline += 0.5
        assert timeout.deadline == _core.current_deadline() == start + 1.5
    assert not timeout.raised
    mock_clock.advance(2)
    await _core.yield_briefly()
    await _core.yield_briefly()
    await _core.yield_briefly()
    assert not timeout.raised

    start = _core.current_time()
    with _core.move_on_at(start + 1) as timeout:
        mock_clock.advance(2)
        await sleep_forever()
    # But then move_on_at swallowed the exception... but we can still see it
    # here:
    assert timeout.raised

    # Nested timeouts: if two fire at once, the outer one wins
    start = _core.current_time()
    with _core.move_on_at(start + 10) as t1:
        with _core.move_on_at(start + 5) as t2:
            with _core.move_on_at(start + 1) as t3:
                mock_clock.advance(7)
                await sleep_forever()
    assert not t3.raised
    assert t2.raised
    assert not t1.raised

    # But you can use a timeout while handling a timeout exception:
    start = _core.current_time()
    with _core.move_on_at(start + 1) as t1:
        try:
            mock_clock.advance(2)
            await sleep_forever()
        except _core.TimeoutCancelled:
            with _core.move_on_at(start + 3) as t2:
                mock_clock.advance(2)
                await sleep_forever()
    assert t1.raised
    assert t2.raised

    # if second timeout is registered while one is *pending* (expired but not
    # yet delivered), then the second timeout will never fire
    start = _core.current_time()
    with _core.move_on_at(start + 1) as t1:
        mock_clock.advance(2)
        # ticking over the event loop makes it notice the timeout
        # expiration... but b/c we use the weird no_cancel thing, it can't be
        # delivered yet, so it becomes pending.
        await _core.yield_briefly_no_cancel()
        with _core.move_on_at(start + 3) as t2:
            try:
                await _core.yield_briefly()
            except _core.TimeoutCancelled:
                # this is the outer timeout:
                assert t1.raised
                # the inner timeout hasn't even reached its expiration time
                assert _core.current_time() < t2.deadline
                # but now if we do pass the deadline, it still won't fire
                mock_clock.advance(2)
                await _core.yield_briefly()
                await _core.yield_briefly()
                await _core.yield_briefly()
                assert t2.deadline < _core.current_time()
    assert not t2.raised

    # if a timeout is pending, but then gets popped off the stack, then it
    # isn't delivered
    start = _core.current_time()
    with _core.move_on_at(start + 1) as t1:
        mock_clock.advance(2)
        await _core.yield_briefly_no_cancel()
    await _core.yield_briefly()
    assert not t1.raised


async def test_timekeeping():
    # probably a good idea to use a real clock for *one* test anyway...
    TARGET = 0.25
    # give it a few tries in case of random CI server flakiness
    for _ in range(4):
        real_start = time.monotonic()
        with _core.move_on_at(_core.current_time() + TARGET):
            await sleep_forever()
        real_duration = time.monotonic() - real_start
        accuracy = real_duration / TARGET
        print(accuracy)
        # Actual time elapsed should always be >= target time
        if 1.0 <= accuracy < 1.2:
            break
    else:  # pragma: no cover
        assert False


async def test_failed_abort():
    record = []
    async def stubborn_sleeper():
        record.append("sleep")
        x = await _core.yield_indefinitely(lambda: _core.Abort.FAILED)
        assert x == 1
        record.append("woke")
        try:
            _core.cancellation_point_no_yield()
        except _core.Cancelled:
            record.append("cancelled")

    task = await _core.spawn(stubborn_sleeper)
    task.cancel_nowait()
    await busy_wait_for(lambda: record)
    _core.reschedule(task, _core.Value(1))
    await task.join()
    assert record == ["sleep", "woke", "cancelled"]


def test_broken_abort():
    async def main():
        # These yields are here to work around an annoying warning -- we're
        # going to crash the main loop, and if we (by chance) do this before
        # the call_soon_task runs for the first time, then Python gives us a
        # spurious warning about it not being awaited. (I mean, the warning is
        # correct, but here we're testing our ability to kinda-sorta recover
        # after things have gone totally pear-shaped, so it's not relevant.)
        # By letting the call_soon_task run first, we avoid the warning.
        await _core.yield_briefly()
        await _core.yield_briefly()
        _core.current_task().cancel_nowait()
        # None is not a legal return value here
        await _core.yield_indefinitely(lambda: None)
    with pytest.raises(_core.TrioInternalError):
        _core.run(main)


# intentionally make a system task crash (simulates a bug in call_soon_task or
# similar)
def test_system_task_crash():
    async def main():
        # this cheats a bit to set things up -- oh well, if we ever change the
        # internal APIs we can just change the test too.
        runner = _core._runner.GLOBAL_RUN_CONTEXT.runner
        async def crasher():
            raise KeyError
        task = runner.spawn_impl(
            crasher, (), type=_core._runner.TaskType.SYSTEM)
        # Even though we're listening for an error, that's not enough to save
        # us:
        await task.join()

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
    with _core.move_on_at(_core.current_time() + 5):
        await _core.yield_briefly()
        with pytest.raises(_core.Cancelled):
            mock_clock.advance(10)
            await _core.yield_briefly()


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

    t1 = await _core.spawn(child1)
    t2 = await _core.spawn(child2)
    await t1.join()
    await t2.join()

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

    async def async_cb(x):
        await _core.yield_briefly()
        record.append(("async-cb", x))
    record = []
    call_soon(async_cb, 2, spawn=True)
    await busy_wait_for(lambda: len(record) == 1)
    assert record == [("async-cb", 2)]

def test_call_soon_too_late():
    call_soon = None
    async def main():
        nonlocal call_soon
        call_soon = _core.current_call_soon_thread_and_signal_safe()
    _core.run(main)
    assert call_soon is not None
    with pytest.raises(_core.RunFinishedError):
        call_soon(lambda: None)

def test_call_soon_after_crash():
    record = []

    async def crasher():
        record.append("crashed")
        raise ValueError

    async def asynccb():
        record.append("async-cb")
        try:
            await _core.yield_briefly()
        except _core.Cancelled:
            record.append("async-cb cancelled")

    async def main():
        call_soon = _core.current_call_soon_thread_and_signal_safe()
        await _core.spawn(crasher)
        try:
            await busy_wait_for(lambda: False)
        except _core.Cancelled:
            pass
        # After a crash but before exit, sync callback processed normally
        call_soon(lambda: record.append("sync-cb"))
        await busy_wait_for(lambda: "sync-cb" in record)
        # And async callbacks are run, but come "pre-cancelled"
        call_soon(asynccb, spawn=True)
        await busy_wait_for(lambda: "async-cb cancelled" in record)

    with pytest.raises(_core.UnhandledExceptionError):
        _core.run(main)

    assert record == ["crashed", "sync-cb", "async-cb", "async-cb cancelled"]

def test_call_soon_crashes():
    record = []

    async def main():
        call_soon = _core.current_call_soon_thread_and_signal_safe()
        call_soon(lambda: dict()["nope"])
        try:
            await busy_wait_for(lambda: False)
        except _core.Cancelled:
            record.append("cancelled!")

    with pytest.raises(_core.UnhandledExceptionError) as excinfo:
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
    # buffer size is 64 KiB, though we reduce it to 4096.
    COUNT = 66000
    call_soon = _core.current_call_soon_thread_and_signal_safe()
    counter = [0]
    def cb():
        counter[0] += 1
    for _ in range(COUNT):
        call_soon(cb)
    await busy_wait_for(lambda: counter[0] == COUNT)


# XX crash in instrument

# make sure to set up one where all tasks are blocked on I/O to exercise the
# timeout = _MAX_TIMEOUT line

# other files:
# keyboard interrupt: this will be fun...
# queue
# unix IO
# windows IO
