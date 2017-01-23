import threading
from functools import wraps, partial
from contextlib import contextmanager
import inspect
import attr

from . import _core

__all__ = ["busy_wait_for", "wait_run_loop_idle", "trio_test", "MockClock",
           "assert_yields", "assert_no_yields"]

async def busy_wait_for(predicate):
    while not predicate():
        await _core.yield_briefly()

from ._core import wait_run_loop_idle

# Use:
#
#    @trio_test
#    async def test_whatever():
#        await ...
#
# Also: if a pytest fixture is passed in that subclasses the Clock abc, then
# that clock is passed to trio.run().
def trio_test(fn):
    @wraps(fn)
    def wrapper(**kwargs):
        __tracebackhide__ = True
        clocks = [c for c in kwargs.values() if isinstance(c, _core.Clock)]
        if not clocks:
            clock = None
        elif len(clocks) == 1:
            clock = clocks[0]
        else:
            raise ValueError("too many clocks spoil the broth!")
        return _core.run(partial(fn, **kwargs), clock=clock)
    return wrapper

# Prior art:
#   https://twistedmatrix.com/documents/current/api/twisted.internet.task.Clock.html
#   https://github.com/ztellman/manifold/issues/57
@attr.s(slots=True, cmp=False, hash=False)
class MockClock(_core.Clock):
    _mock_time = attr.ib(convert=float, default=0.0)

    # XX could also have pause/unpause functionality to start it running in
    # real time... is that useful?

    def current_time(self):
        return self._mock_time

    def deadline_to_sleep_time(self, deadline):
        if deadline <= self._mock_time:
            return 0
        else:
            return 999999999

    def advance(self, offset):
        if offset < 0:
            raise ValueError("time can't go backwards")
        self._mock_time += offset

    # async def pump(self, offsets):
    #     for offset in offsets:
    #         self.advance(offset)
    #         await _core.yield_briefly()
    #         await _core.yield_briefly()


@attr.s(cmp=False, hash=False)
class _RecordYield(_core.Instrument):
    yielded = attr.ib(default=False)

    def after_task_step(self, task):
        self.yielded = True

@contextmanager
def _assert_yields_or_not(expected):
    __tracebackhide__ = True
    instrument = _RecordYield()
    _core.current_instruments().append(instrument)
    try:
        yield
    finally:
        assert instrument.yielded == expected

def assert_yields():
    __tracebackhide__ = True
    return _assert_yields_or_not(True)

def assert_no_yields():
    __tracebackhide__ = True
    return _assert_yields_or_not(False)


# XX Sequencer like in volley/jongleur
# refinements:
# - ability to schedule clock advancements
# - tick over the event loop between steps, so timeouts have a chance to fire?
#   - a random number of times? until quiescent?
#
# another idea: have a fixed number of parallel tasks set at init, and then
# they all go in lockstep

async def task1():
    await seq(0, 1, 2)
    # in step 2
    await seq(3)
    # in step 3

async def task2():
    await seq(0)
    # in step 0
    await seq(1, 2)
