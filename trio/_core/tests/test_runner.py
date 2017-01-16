import pytest
import attr

from ... import _core

def check_exc_chain(exc, chain, complete=True):
    while chain:
        assert type(exc) is chain.pop(0)
        if chain:
            exc = getattr(exc, "__{}__".format(chain.pop(0)))
    if complete:
        assert exc.__cause__ is None
        assert exc.__context__ is None

# Example:
#   check_exc_chain(
#     exc, [UnhandledExceptionError, "cause", KeyError, "context", ...]

def test_check_exc_chain():
    exc = ValueError()
    exc.__context__ = KeyError()
    exc.__context__.__cause__ = RuntimeError()
    exc.__context__.__cause__.__cause__ = TypeError()

    check_exc_chain(exc, [
        ValueError, "context", KeyError, "cause", RuntimeError, "cause",
        TypeError,
    ])
    with pytest.raises(AssertionError):
        check_exc_chain(exc, [
            NameError, "context", KeyError, "cause", RuntimeError, "cause",
            TypeError,
        ])
    with pytest.raises(AssertionError):
        check_exc_chain(exc, [
            ValueError, "cause", KeyError, "cause", RuntimeError, "cause",
            TypeError,
        ])
    with pytest.raises(AssertionError):
        check_exc_chain(exc, [
            ValueError, "context", KeyError, "cause", RuntimeError, "cause",
            NameError,
        ])


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
        async def main():
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

    # This test will break if we ever switch away from pure FIFO scheduling,
    # but for now this should be 100% reliable:
    assert record == [("a", 0), ("b", 0),
                      ("a", 1), ("b", 1),
                      ("a", 2), ("b", 2)]


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
    import time
    t_in_between = time.monotonic()
    t2 = _core.current_time()
    assert t1 < t_in_between < t2

async def test_current_time_with_mock_clock(mock_clock):
    start = mock_clock.current_time()
    assert mock_clock.current_time() == _core.current_time()
    assert mock_clock.current_time() == _core.current_time()
    await mock_clock.advance(3.14)
    assert start + 3.14 == mock_clock.current_time() == _core.current_time()


async def test_current_task():
    async def child():
        return _core.current_task()

    child_task = await _core.spawn(child)
    assert child_task == (await child_task.join()).unwrap()


def is_subsequence(sub, sup):
    it = iter(sup)
    # trick: 'obj in it' consumes items from 'it' until it finds 'obj'
    # https://stackoverflow.com/questions/24017363/how-to-test-if-one-string-is-a-subsequence-of-another
    return all(obj in it for obj in sub)

def test_is_subsequence():
    assert is_subsequence([1, 3], range(5))
    assert not is_subsequence([1, 3, 5], range(5))
    assert not is_subsequence([3, 1], range(5))

def test_profilers():
    @attr.s
    class Recorder(_core.Profiler):
        record = attr.ib(default=attr.Factory(list))

        def before_task_step(self, task):
            self.record.append(("before", task))

        def after_task_step(self, task):
            self.record.append(("after", task))

        def close(self):
            self.record.append(("close",))

    r1 = Recorder()
    r2 = Recorder()
    r3 = Recorder()

    async def main():
        for _ in range(2):
            await _core.yield_briefly()
        cp = _core.current_profilers()
        assert cp == [r1, r2]
        # replace r2 with r3, to test that we can manipulate them as we go
        cp[1] = r3
        for _ in range(1):
            await _core.yield_briefly()
        return _core.current_task()
    main_task = _core.run(main, profilers=[r1, r2])
    expected = [("before", main_task), ("after", main_task),
                ("before", main_task), ("after", main_task),
                ("before", main_task), ("after", main_task),
                ("close",)]
    assert len(r1.record) > len(r2.record) > len(r3.record)
    assert r1.record == r2.record + r3.record
    # Need subsequence check b/c there's also the system task bumping around
    # in the record:
    assert is_subsequence(expected, r1.record)

    # since we had no
    assert len(r1.record) == len(expected) + 4


# cancellation:
# cancel (not just cancel_nowait)
# cancel twice -> should error out I think
# timeouts:
# - cancel_after
#   - the status stuff
#   - nesting
# - ugh so many edge cases

# yield_briefly_no_cancel
# synthetic test of yield_indefinitely + reschedule
# cancellation_point_no_yield
# - current_deadline


# this needs basic basic IOCP stuff and MacOS testing:
# call soon
# - without spawn
# - with spawn
# - after run has exited
# - after a task has crashed
# - callback crashes
# - thread pumping lots of callbacks in doesn't starve out everyone else
#   - put in 100 callbacks (from main thread, why not), and check that they're
#     at least somewhat interleaved with a looping thread
#


# other files:
# keyboard interrupt: this will be fun...
# parking lot
# queue
# unix IO
# windows IO
