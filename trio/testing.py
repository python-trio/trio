import threading
from functools import wraps, partial
from contextlib import contextmanager
import inspect
from collections import defaultdict
import time
from math import inf

import attr
from async_generator import async_generator, yield_

from ._util import acontextmanager
from . import _core
from . import Event, sleep
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
class MockClock(Clock):
    """A user-controllable clock suitable for writing tests.

    Args:
      rate (float): the initial :attr:`rate`.
      autojump_threshold (float): the initial :attr:`autojump_threshold`.

    .. attribute:: rate

       How many seconds of clock time pass per second of real time. Default is
       0.0, i.e. the clock only advances through manuals calls to :meth:`jump`
       or when the :attr:`autojump_threshold` is triggered. You can assign to
       this attribute to change it.

    .. attribute:: autojump_threshold

       If all tasks are blocked for this many real seconds (i.e., according to
       the actual clock, not this clock), then this clock automatically jumps
       ahead to the run loop's next scheduled timeout. Default is
       :data:`math.inf`, i.e., to never autojump. You can assign to this
       attribute to change it.

       You should set this to the smallest value that lets you reliably avoid
       "false alarms" where some I/O is in flight (e.g. between two halves of
       a socketpair) but the threshold gets triggered and time gets advanced
       anyway. This will depend on the details of your tests and test
       environment. If you aren't doing any I/O (like in our sleeping example
       above) then setting it to zero is fine.

       Note that setting this attribute interacts with the run loop, so can
       only be done from inside a run context or (as a special case) before
       calling :func:`trio.run`.

       .. warning::

          If you're using :func:`wait_all_tasks_blocked` and
          :attr:`autojump_threshold` together, then you have to be
          careful. Setting :attr:`autojump_threshold` acts like a task
          calling::

             while True:
                 await wait_all_tasks_blocked(cushion=clock.autojump_threshold)

          This means that if you call :func:`wait_all_tasks_blocked` with a
          cushion *larger* than your autojump threshold, then your call to
          :func:`wait_all_tasks_blocked` will never return, because the
          autojump task will keep waking up before your task does, and each
          time it does it'll reset your task's timer.

          tl;dr: you should set :attr:`autojump_threshold` to be at least as
          large as the largest cushion you plan to pass to
          :func:`wait_all_tasks_blocked`.

    """

    def __init__(self, rate=0.0, autojump_threshold=inf):
        # when the real clock said 'real_base', the virtual time was
        # 'virtual_base', and since then it's advanced at 'rate' virtual
        # seconds per real second.
        self._real_base = 0.0
        self._virtual_base = 0.0
        self._rate = 0.0
        self._autojump_threshold = 0.0
        self._autojump_task = None
        self._autojump_cancel_scope = None
        # kept as an attribute so that our tests can monkeypatch it
        self._real_clock = time.monotonic

        # use the property update logic to set initial values
        self.rate = rate
        self.autojump_threshold = autojump_threshold

    def __repr__(self):
        return ("<MockClock, time={:.7f}, rate={} @ {:#x}>"
                .format(self.current_time(), self._rate, id(self)))

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
            self._rate = float(new_rate)

    @property
    def autojump_threshold(self):
        return self._autojump_threshold

    async def _autojumper(self):
        while True:
            with _core.open_cancel_scope() as cancel_scope:
                self._autojump_cancel_scope = cancel_scope
                try:
                    # If the autojump_threshold changes, then the setter does
                    # cancel_scope.cancel() ,which causes this line to raise
                    # Cancelled, which is absorbed by the cancel scope above,
                    # and effectively just causes us to skip start the loop
                    # over, like a 'continue' here.
                    await wait_all_tasks_blocked(self._autojump_threshold)
                    statistics = _core.current_statistics()
                    jump = statistics.seconds_to_next_deadline
                    if jump < inf:
                        self.jump(jump)
                    else:
                        # There are no deadlines, nothing is going to happen
                        # until some actual I/O arrives (or maybe another
                        # wait_all_tasks_blocked task wakes up). That's fine,
                        # but if our threshold is zero then this will become a
                        # busy-wait -- so insert a small-but-non-zero sleep to
                        # avoid that.
                        if self._autojump_threshold == 0:
                            await wait_all_tasks_blocked(0.01)
                finally:
                    self._autojump_cancel_scope = None

    def _maybe_spawn_autojump_task(self):
        if self._autojump_threshold < inf and self._autojump_task is None:
            try:
                clock = _core.current_clock()
            except RuntimeError:
                return
            if clock is self:
                self._autojump_task = _core.spawn_system_task(self._autojumper)

    @autojump_threshold.setter
    def autojump_threshold(self, new_autojump_threshold):
        self._autojump_threshold = float(new_autojump_threshold)
        self._maybe_spawn_autojump_task()
        if self._autojump_cancel_scope is not None:
            # Task is running and currently blocked on the old setting, wake
            # it up so it picks up the new setting
            self._autojump_cancel_scope.cancel()

    def _real_to_virtual(self, real):
        real_offset = real - self._real_base
        virtual_offset = self._rate * real_offset
        return self._virtual_base + virtual_offset

    def start_clock(self):
        call_soon = _core.current_call_soon_thread_and_signal_safe()
        call_soon(self._maybe_spawn_autojump_task)

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

    def jump(self, seconds):
        """Manually advance the clock by the given number of seconds.

        Args:
          seconds (float): the number of seconds to jump the clock forward.

        Raises:
          ValueError: if you try to pass a negative ``seconds``

        """
        if seconds < 0:
            raise ValueError("time can't go backwards")
        self._virtual_base += seconds


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
