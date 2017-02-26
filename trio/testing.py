import threading
from functools import wraps, partial
from contextlib import contextmanager
import inspect
from collections import defaultdict
import time

import attr
from async_generator import async_generator, yield_

from ._util import acontextmanager
from . import _core
from . import Event
from .abc import Clock

__all__ = ["busy_wait_for", "wait_run_loop_idle", "trio_test", "MockClock",
           "assert_yields", "assert_no_yields", "Sequencer"]

async def busy_wait_for(predicate):
    while not predicate():
        await _core.yield_briefly()
        # Sometimes we're waiting for things in other threads, so best to
        # yield the CPU as well.
        time.sleep(0)

# re-export
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
        clocks = [c for c in kwargs.values() if isinstance(c, Clock)]
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
class MockClock(Clock):
    _mock_time = attr.ib(convert=float, default=0.0, init=False)

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


@attr.s(cmp=False, hash=False)
class _RecordYieldInstrument:
    yielded = attr.ib(default=False)

    def after_task_step(self, task):
        self.yielded = True

@contextmanager
def _assert_yields_or_not(expected):
    __tracebackhide__ = True
    instrument = _RecordYieldInstrument()
    _core.current_instruments().append(instrument)
    try:
        yield
    finally:
        if expected:
            assert instrument.yielded, "assert_yields block did not yield!"
        else:
            assert not instrument.yielded, "assert_no_yields block yielded!"

def assert_yields():
    __tracebackhide__ = True
    return _assert_yields_or_not(True)

def assert_no_yields():
    __tracebackhide__ = True
    return _assert_yields_or_not(False)


@attr.s(slots=True, cmp=False, hash=False)
class Sequencer:
    _sequence_points = attr.ib(
        default=attr.Factory(lambda: defaultdict(Event)), init=False)
    _claimed = attr.ib(default=attr.Factory(set), init=False)
    _broken = attr.ib(default=False, init=False)

    @acontextmanager
    @async_generator
    async def __call__(self, position):
        if position in self._claimed:
            raise RuntimeError(
                "Attempted to re-use sequence point {}".format(position))
        if self._broken:
            raise RuntimeError("sequence broken!")
        self._claimed.add(position)
        if position != 0:
            try:
                await self._sequence_points[position].wait()
            except _core.Cancelled:
                self._broken = True
                for event in self._sequence_points.values():
                    event.set()
                raise RuntimeError(
                    "Sequencer wait cancelled -- sequence broken")
            else:
                if self._broken:
                    raise RuntimeError("sequence broken!")
        try:
            await yield_()
        finally:
            self._sequence_points[position + 1].set()
