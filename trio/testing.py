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

__all__ = ["wait_all_tasks_blocked", "trio_test", "MockClock",
           "assert_yields", "assert_no_yields", "Sequencer"]

# re-export
from ._core import wait_all_tasks_blocked

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
@attr.s(slots=True, cmp=False, hash=False, repr=False)
class MockClock(Clock):
    """A user-controllable clock suitable for writing tests.

    This clock starts at time 0, and advances at the given rate relative to
    real time. Can also be manually stepped by calling :meth:`advance`.

    Args:
      rate (float): the initial :attr:`rate`.

    .. attribute:: rate

       How many seconds of clock time pass per second of real time. Default is
       0.0, i.e. the clock only advances through manuals calls to
       :meth:`advance`. You can assign to this attribute to change it.

    """

    # When the real clock read "_real_base", our time was "_virtual_base"
    _real_base = attr.ib(convert=float, default=0.0, init=False)
    _virtual_base = attr.ib(convert=float, default=0.0, init=False)
    # How many seconds our clock has advanced since then, per second of real
    # time
    _rate = attr.ib(convert=float, default=0.0, init=True)
    # overrideable for purposes of our own tests:
    _real_clock = attr.ib(default=time.monotonic, init=False)

    def __repr__(self):
        return ("<MockClock, time={:.7f}, rate={}>"
                .format(self.current_time(), self._rate))

    @property
    def rate(self):
        return self._rate

    @rate.setter
    def rate(self, new_rate):
        if new_rate < 0:
            raise ValueError("rate must be >= 0")
        else:
            real = self._real_clock()
            virtual = self._real_to_virtual(real)
            self._virtual_base = virtual
            self._real_base = real
            self._rate = new_rate

    def _real_to_virtual(self, real):
        real_offset = real - self._real_base
        virtual_offset = self._rate * real_offset
        return self._virtual_base + virtual_offset

    def current_time(self):
        return self._real_to_virtual(self._real_clock())

    def deadline_to_sleep_time(self, deadline):
        virtual_timeout = deadline - self.current_time()
        if virtual_timeout <= 0:
            return 0
        elif self._rate > 0:
            return virtual_timeout / self._rate
        else:
            return 999999999

    def advance(self, offset):
        """Advance the clock.

        Args:
          offset (float): the number of seconds to advance the clock.

        """
        if offset < 0:
            raise ValueError("time can't go backwards")
        self._virtual_base += offset


@contextmanager
def _assert_yields_or_not(expected):
    __tracebackhide__ = True
    task = _core.current_task()
    orig_cancel = task._cancel_points
    orig_schedule = task._schedule_points
    try:
        yield
    finally:
        if (expected
            and (task._cancel_points == orig_cancel
                 or task._schedule_points == orig_schedule)):
            raise AssertionError("assert_yields block did not yield!")
        elif (not expected
              and (task._cancel_points != orig_cancel
                   or task._schedule_points != orig_schedule)):
            raise AssertionError("assert_no_yields block yielded!")

def assert_yields():
    """Use as a context manager to check that the code inside the ``with``
    block executes at least one :ref:`yield point <yield-points>`.

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
    """Use as a context manager to check that the code inside the ``with``
    block does not execute any :ref:`yield points <yield-points>`.

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
