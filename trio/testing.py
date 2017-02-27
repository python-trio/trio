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
    """A crude but useful way to wait for a predicate to become true.

    Args:
      predicate: A zero-argument callable that returns a bool.

    """
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
    """A user-controllable clock suitable for writing tests.

    This clock starts at time 0, and only advances when explicitly requested.

    """

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
        """Advance the clock by ``offset`` seconds.

        """
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
        if expected and not instrument.yielded:
            raise AssertionError("assert_yields block did not yield!")
        elif not expected and instrument.yielded:
            raise AssertionError("assert_no_yields block yielded!")

def assert_yields():
    """Check that a block of code executes at least one yield point.

    Use as a context manager to check that the code inside the ``with`` block
    executes at least one :ref:`yield point <yield-points>`.

    Raises:
      AssertionError: if no yield point was executed.

    Example:
      Check that :func:`trio.sleep` is a yield point, even if it doesn't
      block::

         with trio.testing.assert_yields():
             await trio.sleep(0)

    """
    __tracebackhide__ = True
    return _assert_yields_or_not(True)

def assert_no_yields():
    """Check that a block of code does not execute any yield points.

    Use as a context manager to check that the code inside the ``with`` block
    does not execute any :ref:`yield points <yield-points>`.

    Raises:
      AssertionError: if a yield point was executed.

    Example:
      Synchronous code never yields, but we can double-check that::

         queue = trio.Queue(10)
         with trio.testing.assert_no_yields():
             queue.put_nowait(None)

    """
    __tracebackhide__ = True
    return _assert_yields_or_not(False)


@attr.s(slots=True, cmp=False, hash=False)
class Sequencer:
    """A convenience class for forcing code in different tasks to run in an
    explicit linear order.

    Instances of this class implement a ``__call__`` method which returns an
    async context manager. The idea is that you pass a sequence number to
    ``__call__`` to say where this block of code should go in the linear
    sequence. Block 0 starts immediately, and then block N doesn't start until
    block N-1 has finished.

    Example:
      An extremely elaborate way to print the numbers 0-5, in order::

         async def worker1(seq):
             async with seq(0):
                 print(0)
             async with seq(4):
                 print(4)

         async def worker2(seq):
             async with seq(2):
                 print(2)
             async with seq(5):
                 print(5)

         async def worker3(seq):
             async with seq(1):
                 print(1)
             async with seq(3):
                 print(3)

         async def main():
            seq = trio.testing.Sequencer()
            async with trio.open_nursery() as nursery:
                nursery.spawn(worker1, seq)
                nursery.spawn(worker2, seq)
                nursery.spawn(worker3, seq)

    """

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
