import threading
from functools import wraps, partial
from contextlib import contextmanager
import inspect
from collections import defaultdict
import time
from math import inf
import random
import operator

import attr
from async_generator import async_generator, yield_

from . import _util
from . import _core
from . import _streams
from . import Event as _Event, sleep as _sleep
from . import abc as _abc

__all__ = [
    "wait_all_tasks_blocked", "trio_test", "MockClock",
    "assert_yields", "assert_no_yields", "Sequencer",
    "MemorySendStream", "MemoryReceiveStream", "memory_stream_pump",
    "memory_stream_one_way_pair", "memory_stream_pair",
    "lockstep_stream_one_way_pair", "lockstep_stream_pair",
    "check_one_way_stream", "check_two_way_stream",
    "check_half_closeable_stream",
]

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
        clocks = [c for c in kwargs.values() if isinstance(c, _abc.Clock)]
        if not clocks:
            clock = None
        elif len(clocks) == 1:
            clock = clocks[0]
        else:
            raise ValueError("too many clocks spoil the broth!")
        return _core.run(partial(fn, **kwargs), clock=clock)
    return wrapper


################################################################
# The glorious MockClock
################################################################

# Prior art:
#   https://twistedmatrix.com/documents/current/api/twisted.internet.task.Clock.html
#   https://github.com/ztellman/manifold/issues/57
class MockClock(_abc.Clock):
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

       The clock keeps an eye on the run loop, and if at any point it detects
       that all tasks have been blocked for this many real seconds (i.e.,
       according to the actual clock, not this clock), then the clock
       automatically jumps ahead to the run loop's next scheduled
       timeout. Default is :data:`math.inf`, i.e., to never autojump. You can
       assign to this attribute to change it.

       Basically the idea is that if you have code or tests that use sleeps
       and timeouts, you can use this to make it run much faster, totally
       automatically. (At least, as long as those sleeps/timeouts are
       happening inside trio; if your test involves talking to external
       service and waiting for it to timeout then obviously we can't help you
       there.)

       You should set this to the smallest value that lets you reliably avoid
       "false alarms" where some I/O is in flight (e.g. between two halves of
       a socketpair) but the threshold gets triggered and time gets advanced
       anyway. This will depend on the details of your tests and test
       environment. If you aren't doing any I/O (like in our sleeping example
       above) then just set it to zero, and the clock will jump whenever all
       tasks are blocked.

       .. warning::

          If you're using :func:`wait_all_tasks_blocked` and
          :attr:`autojump_threshold` together, then you have to be
          careful. Setting :attr:`autojump_threshold` acts like a background
          task calling::

             while True:
                 await wait_all_tasks_blocked(
                   cushion=clock.autojump_threshold, tiebreaker=float("inf"))

          This means that if you call :func:`wait_all_tasks_blocked` with a
          cushion *larger* than your autojump threshold, then your call to
          :func:`wait_all_tasks_blocked` will never return, because the
          autojump task will keep waking up before your task does, and each
          time it does it'll reset your task's timer. However, if your cushion
          and the autojump threshold are the *same*, then the autojump's
          tiebreaker will prevent them from interfering (unless you also set
          your tiebreaker to infinity for some reason. Don't do that). As an
          important special case: this means that if you set an autojump
          threshold of zero and use :func:`wait_all_tasks_blocked` with the
          default zero cushion, then everything will work fine.

          **Summary**: you should set :attr:`autojump_threshold` to be at
          least as large as the largest cushion you plan to pass to
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
                    # cancel_scope.cancel(), which causes the next line here
                    # to raise Cancelled, which is absorbed by the cancel
                    # scope above, and effectively just causes us to skip back
                    # to the start the loop, like a 'continue'.
                    await wait_all_tasks_blocked(
                        self._autojump_threshold, float("inf"))
                    statistics = _core.current_statistics()
                    jump = statistics.seconds_to_next_deadline
                    if jump < inf:
                        self.jump(jump)
                    else:
                        # There are no deadlines, nothing is going to happen
                        # until some actual I/O arrives (or maybe another
                        # wait_all_tasks_blocked task wakes up). That's fine,
                        # but if our threshold is zero then this will become a
                        # busy-wait -- so insert a small-but-non-zero _sleep to
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
          ValueError: if you try to pass a negative value for ``seconds``.

        """
        if seconds < 0:
            raise ValueError("time can't go backwards")
        self._virtual_base += seconds


################################################################
# Testing checkpoints
################################################################

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
    block executes at least one :ref:`checkpoint <checkpoints>`.

    Raises:
      AssertionError: if no checkpoint was executed.

    Example:
      Check that :func:`trio.sleep` is a checkpoint, even if it doesn't
      block::

         with trio.testing.assert_yields():
             await trio.sleep(0)

    """
    __tracebackhide__ = True
    return _assert_yields_or_not(True)

def assert_no_yields():
    """Use as a context manager to check that the code inside the ``with``
    block does not execute any :ref:`check points <checkpoints>`.

    Raises:
      AssertionError: if a checkpoint was executed.

    Example:
      Synchronous code never yields, but we can double-check that::

         queue = trio.Queue(10)
         with trio.testing.assert_no_yields():
             queue.put_nowait(None)

    """
    __tracebackhide__ = True
    return _assert_yields_or_not(False)


################################################################
# Sequencer
################################################################

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
        default=attr.Factory(lambda: defaultdict(_Event)), init=False)
    _claimed = attr.ib(default=attr.Factory(set), init=False)
    _broken = attr.ib(default=False, init=False)

    @_util.acontextmanager
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


################################################################
# Generic stream tests
################################################################

class _CloseBoth:
    def __init__(self, both):
        self._both = list(both)

    async def __aenter__(self):
        return self._both

    async def __aexit__(self, *args):
        try:
            self._both[0].forceful_close()
        finally:
            self._both[1].forceful_close()


@contextmanager
def _assert_raises(exc):
    __tracebackhide__ = True
    try:
        yield
    except exc:
        pass
    else:
        raise AssertionError("expected exception: {}".format(exc))


async def check_one_way_stream(stream_maker, clogged_stream_maker):
    """Perform a number of generic tests on a custom one-way stream
    implementation.

    Args:
      stream_maker: An async (!) function which returns a connected
          (:class:`~trio.abc.SendStream`, :class:`~trio.abc.ReceiveStream`)
          pair.
      clogged_stream_maker: Either None, or an async function similar to
          stream_maker, but with the extra property that the returned stream
          is in a state where ``send_all`` and
          ``wait_send_all_might_not_block`` will block until ``receive_some``
          has been called. This allows for more thorough testing of some edge
          cases, especially around ``wait_send_all_might_not_block``.

    Raises:
      AssertionError: if a test fails.

    """
    async with _CloseBoth(await stream_maker()) as (s, r):
        assert isinstance(s, _abc.SendStream)
        assert isinstance(r, _abc.ReceiveStream)

        async def do_send_all(data):
            with assert_yields():
                assert await s.send_all(data) is None

        async def do_receive_some(max_bytes):
            with assert_yields():
                return await r.receive_some(1)

        async def checked_receive_1(expected):
            assert await do_receive_some(1) == expected

        async def do_graceful_close(resource):
            with assert_yields():
                await resource.graceful_close()

        # Simple sending/receiving
        async with _core.open_nursery() as nursery:
            nursery.spawn(do_send_all, b"x")
            nursery.spawn(checked_receive_1, b"x")

        async def send_empty_then_y():
            # Streams should tolerate sending b"" without giving it any
            # special meaning.
            await do_send_all(b"")
            await do_send_all(b"y")

        async with _core.open_nursery() as nursery:
            nursery.spawn(send_empty_then_y)
            nursery.spawn(checked_receive_1, b"y")

        ### Checking various argument types

        # send_all accepts bytearray and memoryview
        async with _core.open_nursery() as nursery:
            nursery.spawn(do_send_all, bytearray(b"1"))
            nursery.spawn(checked_receive_1, b"1")

        async with _core.open_nursery() as nursery:
            nursery.spawn(do_send_all, memoryview(b"2"))
            nursery.spawn(checked_receive_1, b"2")

        # max_bytes must be a positive integer
        with _assert_raises(ValueError):
            await r.receive_some(-1)
        with _assert_raises(ValueError):
            await r.receive_some(0)
        with _assert_raises(TypeError):
            await r.receive_some(1.5)

        with _assert_raises(_core.ResourceBusyError):
            async with _core.open_nursery() as nursery:
                nursery.spawn(do_receive_some, 1)
                nursery.spawn(do_receive_some, 1)

        # Method always has to exist, and an empty stream with a blocked
        # receive_some should *always* allow send_all. (Technically it's legal
        # for send_all to wait until receive_some is called to run, though; a
        # stream doesn't *have* to have any internal buffering. That's why we
        # spawn a concurrent receive_some call, then cancel it.)
        async def simple_check_wait_send_all_might_not_block(scope):
            with assert_yields():
                await s.wait_send_all_might_not_block()
            scope.cancel()

        async with _core.open_nursery() as nursery:
            nursery.spawn(simple_check_wait_send_all_might_not_block,
                          nursery.cancel_scope)
            nursery.spawn(do_receive_some, 1)

        # closing the r side
        await do_graceful_close(r)

        # ...leads to BrokenStreamError on the s side (eventually)
        with _assert_raises(_streams.BrokenStreamError):
            while True:
                await do_send_all(b"x" * 100)

        # once detected, the stream stays broken
        with _assert_raises(_streams.BrokenStreamError):
            await do_send_all(b"x" * 100)

        # r closed -> ClosedStreamError on the receive side
        with _assert_raises(_streams.ClosedStreamError):
            await do_receive_some(4096)

        # we can close the same stream repeatedly, it's fine
        r.forceful_close()
        with assert_yields():
            await r.graceful_close()
        r.forceful_close()

        # closing the sender side
        with assert_yields():
            await s.graceful_close()

        # now trying to send raises ClosedStreamError
        with _assert_raises(_streams.ClosedStreamError):
            await do_send_all(b"x" * 100)

        # and again, repeated closing is fine
        s.forceful_close()
        await do_graceful_close(s)
        s.forceful_close()

    async with _CloseBoth(await stream_maker()) as (s, r):
        # if send-then-graceful-close, receiver gets data then b""
        async def send_then_close():
            await do_send_all(b"y")
            await do_graceful_close(s)

        async def receive_send_then_close():
            # We want to make sure that if the sender closes the stream before
            # we read anything, then we still get all the data. But some
            # streams might block on the do_send_all call. So we let the
            # sender get as far as it can, then we receive.
            await wait_all_tasks_blocked()
            await checked_receive_1(b"y")
            await checked_receive_1(b"")

        async with _core.open_nursery() as nursery:
            nursery.spawn(send_then_close)
            nursery.spawn(receive_send_then_close)

    # using forceful_close also makes things closed
    async with _CloseBoth(await stream_maker()) as (s, r):
        r.forceful_close()

        with _assert_raises(_streams.BrokenStreamError):
            while True:
                await do_send_all(b"x" * 100)

        with _assert_raises(_streams.ClosedStreamError):
            await do_receive_some(4096)

    async with _CloseBoth(await stream_maker()) as (s, r):
        s.forceful_close()

        with _assert_raises(_streams.ClosedStreamError):
            await do_send_all(b"123")

        # after the sender does a forceful close, the receiver might either
        # get BrokenStreamError or a clean b""; either is OK. Not OK would be
        # if it freezes, or returns data.
        try:
            await checked_receive_1(b"")
        except _streams.BrokenStreamError:
            pass

    # cancelled graceful_close still closes
    async with _CloseBoth(await stream_maker()) as (s, r):
        with _core.open_cancel_scope() as scope:
            scope.cancel()
            await r.graceful_close()

        with _core.open_cancel_scope() as scope:
            scope.cancel()
            await s.graceful_close()

        with _assert_raises(_streams.ClosedStreamError):
            await do_send_all(b"123")

        with _assert_raises(_streams.ClosedStreamError):
            await do_receive_some(4096)

    # Check that we can still gracefully close a stream after an operation has
    # been cancelled. This can be challenging if cancellation can leave the
    # stream internals in an inconsistent state, e.g. for
    # SSLStream. Unfortunately this test isn't very thorough; the really
    # challenging case for something like SSLStream is it gets cancelled
    # *while* it's sending data on the underlying, not before. But testing
    # that requires some special-case handling of the particular stream setup;
    # we can't do it here. Maybe we could do a bit better with
    #     https://github.com/python-trio/trio/issues/77
    async with _CloseBoth(await stream_maker()) as (s, r):
        async def expect_cancelled(afn, *args):
            with _assert_raises(_core.Cancelled):
                await afn(*args)

        with _core.open_cancel_scope() as scope:
            scope.cancel()
            async with _core.open_nursery() as nursery:
                nursery.spawn(expect_cancelled, do_send_all, b"x")
                nursery.spawn(expect_cancelled, do_receive_some, 1)

        await do_graceful_close(s)
        await do_graceful_close(r)

    # check wait_send_all_might_not_block, if we can
    if clogged_stream_maker is not None:
        async with _CloseBoth(await clogged_stream_maker()) as (s, r):
            record = []

            async def waiter(cancel_scope):
                record.append("waiter sleeping")
                with assert_yields():
                    await s.wait_send_all_might_not_block()
                record.append("waiter wokeup")
                cancel_scope.cancel()

            async def receiver():
                # give wait_send_all_might_not_block a chance to block
                await wait_all_tasks_blocked()
                record.append("receiver starting")
                while True:
                    await r.receive_some(16834)

            async with _core.open_nursery() as nursery:
                nursery.spawn(waiter, nursery.cancel_scope)
                await wait_all_tasks_blocked()
                nursery.spawn(receiver)

            assert record == [
                "waiter sleeping",
                "receiver starting",
                "waiter wokeup",
            ]

        async with _CloseBoth(await clogged_stream_maker()) as (s, r):
            # simultaneous wait_send_all_might_not_block fails
            with _assert_raises(_core.ResourceBusyError):
                async with _core.open_nursery() as nursery:
                    nursery.spawn(s.wait_send_all_might_not_block)
                    nursery.spawn(s.wait_send_all_might_not_block)

            # and simultaneous send_all and wait_send_all_might_not_block (NB
            # this test might destroy the stream b/c we end up cancelling
            # send_all and e.g. SSLStream can't handle that, so we have to
            # recreate afterwards)
            with _assert_raises(_core.ResourceBusyError):
                async with _core.open_nursery() as nursery:
                    nursery.spawn(s.wait_send_all_might_not_block)
                    nursery.spawn(s.send_all, b"123")

        async with _CloseBoth(await clogged_stream_maker()) as (s, r):
            # send_all and send_all blocked simultaneously should also raise
            # (but again this might destroy the stream)
            with _assert_raises(_core.ResourceBusyError):
                async with _core.open_nursery() as nursery:
                    nursery.spawn(s.send_all, b"123")
                    nursery.spawn(s.send_all, b"123")


async def check_two_way_stream(stream_maker, clogged_stream_maker):
    """Perform a number of generic tests on a custom two-way stream
    implementation.

    This is similar to :func:`check_one_way_stream`, except that the maker
    functions are expected to return objects implementing the
    :class:`~trio.abc.Stream` interface.

    This function tests a *superset* of what :func:`check_one_way_stream`
    checks – if you call this, then you don't need to also call
    :func:`check_one_way_stream`.

    """
    await check_one_way_stream(stream_maker, clogged_stream_maker)

    async def flipped_stream_maker():
        return reversed(await stream_maker())
    if clogged_stream_maker is not None:
        async def flipped_clogged_stream_maker():
            return reversed(await clogged_stream_maker())
    else:
        flipped_clogged_stream_maker = None
    await check_one_way_stream(
        flipped_stream_maker, flipped_clogged_stream_maker)

    async with _CloseBoth(await stream_maker()) as (s1, s2):
        assert isinstance(s1, _abc.Stream)
        assert isinstance(s2, _abc.Stream)

        # Duplex can be a bit tricky, might as well check it as well
        DUPLEX_TEST_SIZE = 2 ** 20
        CHUNK_SIZE_MAX = 2 ** 14

        r = random.Random(0)
        i = r.getrandbits(8 * DUPLEX_TEST_SIZE)
        test_data = i.to_bytes(DUPLEX_TEST_SIZE, "little")

        async def sender(s, data, seed):
            r = random.Random(seed)
            m = memoryview(data)
            while m:
                chunk_size = r.randint(1, CHUNK_SIZE_MAX)
                await s.send_all(m[:chunk_size])
                m = m[chunk_size:]

        async def receiver(s, data, seed):
            r = random.Random(seed)
            got = bytearray()
            while len(got) < len(data):
                chunk = await s.receive_some(r.randint(1, CHUNK_SIZE_MAX))
                assert chunk
                got += chunk
            assert got == data

        async with _core.open_nursery() as nursery:
            nursery.spawn(sender, s1, test_data, 0)
            nursery.spawn(sender, s2, test_data[::-1], 1)
            nursery.spawn(receiver, s1, test_data[::-1], 2)
            nursery.spawn(receiver, s2, test_data, 3)

        await s1.graceful_close()
        assert await s2.receive_some(10) == b""
        await s2.graceful_close()


async def check_half_closeable_stream(stream_maker, clogged_stream_maker):
    """Perform a number of generic tests on a custom half-closeable stream
    implementation.

    This is similar to :func:`check_two_way_stream`, except that the maker
    functions are expected to return objects that implement the
    :class:`~trio.abc.HalfCloseableStream` interface.

    This function tests a *superset* of what :func:`check_two_way_stream`
    checks – if you call this, then you don't need to also call
    :func:`check_two_way_stream`.

    """
    await check_two_way_stream(stream_maker, clogged_stream_maker)

    async with _CloseBoth(await stream_maker()) as (s1, s2):
        assert isinstance(s1, _abc.HalfCloseableStream)
        assert isinstance(s2, _abc.HalfCloseableStream)

        async def send_x_then_eof(s):
            await s.send_all(b"x")
            with assert_yields():
                await s.send_eof()

        async def expect_x_then_eof(r):
            await wait_all_tasks_blocked()
            assert await r.receive_some(10) == b"x"
            assert await r.receive_some(10) == b""

        async with _core.open_nursery() as nursery:
            nursery.spawn(send_x_then_eof, s1)
            nursery.spawn(expect_x_then_eof, s2)

        # now sending is disallowed
        with _assert_raises(_streams.ClosedStreamError):
            await s1.send_all(b"y")

        # but we can do send_eof again
        with assert_yields():
            await s1.send_eof()

        # and we can still send stuff back the other way
        async with _core.open_nursery() as nursery:
            nursery.spawn(send_x_then_eof, s2)
            nursery.spawn(expect_x_then_eof, s1)

    if clogged_stream_maker is not None:
        async with _CloseBoth(await clogged_stream_maker()) as (s1, s2):
            # send_all and send_eof simultaneously is not ok
            with _assert_raises(_core.ResourceBusyError):
                async with _core.open_nursery() as nursery:
                    t = nursery.spawn(s1.send_all, b"x")
                    await wait_all_tasks_blocked()
                    assert t.result is None
                    nursery.spawn(s1.send_eof)

        async with _CloseBoth(await clogged_stream_maker()) as (s1, s2):
            # wait_send_all_might_not_block and send_eof simultaneously is not
            # ok either
            with _assert_raises(_core.ResourceBusyError):
                async with _core.open_nursery() as nursery:
                    t = nursery.spawn(s1.wait_send_all_might_not_block)
                    await wait_all_tasks_blocked()
                    assert t.result is None
                    nursery.spawn(s1.send_eof)


################################################################
# In-memory streams
################################################################

class _UnboundedByteQueue:
    def __init__(self):
        self._data = bytearray()
        self._closed = False
        self._lot = _core.ParkingLot()
        self._fetch_lock = _util.UnLock(
            _core.ResourceBusyError, "another task is already fetching data")

    def close(self):
        self._closed = True
        self._lot.unpark_all()

    def put(self, data):
        if self._closed:
            raise _streams.ClosedStreamError("virtual connection closed")
        self._data += data
        self._lot.unpark_all()

    def _check_max_bytes(self, max_bytes):
        if max_bytes is None:
            return
        max_bytes = operator.index(max_bytes)
        if max_bytes < 1:
            raise ValueError("max_bytes must be >= 1")

    def _get_impl(self, max_bytes):
        assert self._closed or self._data
        if max_bytes is None:
            max_bytes = len(self._data)
        if self._data:
            chunk = self._data[:max_bytes]
            del self._data[:max_bytes]
            assert chunk
            return chunk
        else:
            return bytearray()

    def get_nowait(self, max_bytes=None):
        with self._fetch_lock.sync:
            self._check_max_bytes(max_bytes)
            if not self._closed and not self._data:
                raise _core.WouldBlock
            return self._get_impl(max_bytes)

    async def get(self, max_bytes=None):
        async with self._fetch_lock:
            self._check_max_bytes(max_bytes)
            if not self._closed and not self._data:
                await self._lot.park()
            return self._get_impl(max_bytes)


class MemorySendStream(_abc.SendStream):
    """An in-memory :class:`~trio.abc.SendStream`.

    Args:
      send_all_hook: An async function, or None. Called from
          :meth:`send_all`. Can do whatever you like.
      wait_send_all_might_not_block_hook: An async function, or None. Called
          from :meth:`wait_send_all_might_not_block`. Can do whatever you
          like.
      close_hook: A synchronous function, or None. Called from
          :meth:`forceful_close`. Can do whatever you like.

    .. attribute:: send_all_hook
                   wait_send_all_might_not_block_hook
                   close_hook

       All of these hooks are also exposed as attributes on the object, and
       you can change them at any time.

    """
    def __init__(self,
                 send_all_hook=None,
                 wait_send_all_might_not_block_hook=None,
                 close_hook=None):
        self._lock = _util.UnLock(
            _core.ResourceBusyError, "another task is using this stream")
        self._outgoing = _UnboundedByteQueue()
        self.send_all_hook = send_all_hook
        self.wait_send_all_might_not_block_hook = wait_send_all_might_not_block_hook
        self.close_hook = close_hook

    async def send_all(self, data):
        """Places the given data into the object's internal buffer, and then
        calls the :attr:`send_all_hook` (if any).

        """
        # The lock itself is a checkpoint, but then we also yield inside the
        # lock to give ourselves a chance to detect buggy user code that calls
        # this twice at the same time.
        async with self._lock:
            await _core.yield_briefly()
            self._outgoing.put(data)
            if self.send_all_hook is not None:
                await self.send_all_hook()

    async def wait_send_all_might_not_block(self):
        """Calls the :attr:`wait_send_all_might_not_block_hook` (if any), and
        then returns immediately.

        """
        # The lock itself is a checkpoint, but then we also yield inside the
        # lock to give ourselves a chance to detect buggy user code that calls
        # this twice at the same time.
        async with self._lock:
            await _core.yield_briefly()
            if self.wait_send_all_might_not_block_hook is not None:
                await self.wait_send_all_might_not_block_hook()

    def forceful_close(self):
        """Marks this stream as closed, and then calls the :attr:`close_hook`
        (if any).

        """
        self._outgoing.close()
        if self.close_hook is not None:
            self.close_hook()

    async def get_data(self, max_bytes=None):
        """Retrieves data from the internal buffer, blocking if necessary.

        Args:
          max_bytes (int or None): The maximum amount of data to
              retrieve. None (the default) means to retrieve all the data
              that's present (but still blocks until at least one byte is
              available).

        Returns:
          If this stream has been closed, an empty bytearray. Otherwise, the
          requested data.

        """
        return await self._outgoing.get(max_bytes)

    def get_data_nowait(self, max_bytes=None):
        """Retrieves data from the internal buffer, but doesn't block.

        See :meth:`get_data` for details.

        Raises:
          trio.WouldBlock: if no data is available to retrieve.

        """
        return self._outgoing.get_nowait(max_bytes)


class MemoryReceiveStream(_abc.ReceiveStream):
    """An in-memory :class:`~trio.abc.ReceiveStream`.

    Args:
      receive_some_hook: An async function, or None. Called from
          :meth:`receive_some`. Can do whatever you like.

    .. attribute:: receive_some_hook

       The :attr:`receive_some_hook` is also exposed as an attribute on the
       object, and you can change it at any time.

    """
    def __init__(self, receive_some_hook=None):
        self._lock = _util.UnLock(
            _core.ResourceBusyError, "another task is using this stream")
        self._incoming = _UnboundedByteQueue()
        self._closed = False
        self.receive_some_hook = receive_some_hook

    async def receive_some(self, max_bytes):
        """Calls the :attr:`receive_some_hook` (if any), and then retrieves
        data from the internal buffer, blocking if necessary.

        """
        # The lock itself is a checkpoint, but then we also yield inside the
        # lock to give ourselves a chance to detect buggy user code that calls
        # this twice at the same time.
        async with self._lock:
            await _core.yield_briefly()
            if max_bytes is None:
                raise TypeError("max_bytes must not be None")
            if self._closed:
                raise _streams.ClosedStreamError
            if self.receive_some_hook is not None:
                await self.receive_some_hook()
            return await self._incoming.get(max_bytes)

    def forceful_close(self):
        """Discards any pending data from the internal buffer, and marks this
        stream as closed.

        """
        # discard any pending data
        self._closed = True
        try:
            self._incoming.get_nowait()
        except _core.WouldBlock:
            pass
        self._incoming.close()
        self._closed = True

    def put_data(self, data):
        """Appends the given data to the internal buffer.

        """
        self._incoming.put(data)

    def put_eof(self):
        """Adds an end-of-file marker to the internal buffer.

        """
        self._incoming.close()


def memory_stream_pump(
        memory_send_stream, memory_recieve_stream, *, max_bytes=None):
    """Take data out of the given :class:`MemorySendStream`'s internal buffer,
    and put it into the given :class:`MemoryReceiveStream`'s internal buffer.

    Args:
      memory_send_stream (MemorySendStream): The stream to get data from.
      memory_recieve_stream (MemoryReceiveStream): The stream to put data into.
      max_bytes (int or None): The maximum amount of data to transfer in this
          call, or None to transfer all available data.

    Returns:
      True if it successfully transferred some data, or False if there was no
      data to transfer.

    This is used to implement :func:`memory_stream_one_way_pair` and
    :func:`memory_stream_pair`; see the latter's docstring for an example
    of how you might use it yourself.

    """
    try:
        data = memory_send_stream.get_data_nowait(max_bytes)
    except _core.WouldBlock:
        return False
    try:
        if not data:
            memory_recieve_stream.put_eof()
        else:
            memory_recieve_stream.put_data(data)
    except _streams.ClosedStreamError:
        raise _streams.BrokenStreamError("MemoryReceiveStream was closed")
    return True


def memory_stream_one_way_pair():
    """Create a connected, pure-Python, unidirectional stream with infinite
    buffering and flexible configuration options.

    You can think of this as being a no-operating-system-involved
    trio-streamsified version of :func:`os.pipe` (except that :func:`os.pipe`
    returns the streams in the wrong order – we follow the superior convention
    that data flows from left to right).

    Returns:
      A tuple (:class:`MemorySendStream`, :class:`MemoryReceiveStream`), where
      the :class:`MemorySendStream` has its hooks set up so that it calls
      :func:`memory_stream_pump` from its
      :attr:`~MemorySendStream.send_all_hook` and
      :attr:`~MemorySendStream.close_hook`.

    The end result is that data automatically flows from the
    :class:`MemorySendStream` to the :class:`MemoryReceiveStream`. But you're
    also free to rearrange things however you like. For example, you can
    temporarily set the :attr:`~MemorySendStream.send_all_hook` to None if you
    want to simulate a stall in data transmission. Or see
    :func:`memory_stream_pair` for a more elaborate example.

    """
    send_stream = MemorySendStream()
    recv_stream = MemoryReceiveStream()
    def pump_from_send_stream_to_recv_stream():
        memory_stream_pump(send_stream, recv_stream)
    async def async_pump_from_send_stream_to_recv_stream():
        pump_from_send_stream_to_recv_stream()
    send_stream.send_all_hook = async_pump_from_send_stream_to_recv_stream
    send_stream.close_hook = pump_from_send_stream_to_recv_stream
    return send_stream, recv_stream


def _make_stapled_pair(one_way_pair):
    pipe1_send, pipe1_recv = one_way_pair()
    pipe2_send, pipe2_recv = one_way_pair()
    stream1 = _streams.StapledStream(pipe1_send, pipe2_recv)
    stream2 = _streams.StapledStream(pipe2_send, pipe1_recv)
    return stream1, stream2


def memory_stream_pair():
    """Create a connected, pure-Python, bidirectional stream with infinite
    buffering and flexible configuration options.

    This is a convenience function that creates two one-way streams using
    :func:`memory_stream_one_way_pair`, and then uses
    :class:`~trio.StapledStream` to combine them into a single bidirectional
    stream.

    This is like a no-operating-system-involved, trio-streamsified version of
    :func:`socket.socketpair`.

    Returns:
      A pair of :class:`~trio.StapledStream` objects that are connected so
      that data automatically flows from one to the other in both directions.

    After creating a stream pair, you can send data back and forth, which is
    enough for simple tests::

       left, right = memory_stream_pair()
       await left.send_all(b"123")
       assert await right.receive_some(10) == b"123"
       await right.send_all(b"456")
       assert await left.receive_some(10) == b"456"

    But if you read the docs for :class:`~trio.StapledStream` and
    :func:`memory_stream_one_way_pair`, you'll see that all the pieces
    involved in wiring this up are public APIs, so you can adjust to suit the
    requirements of your tests. For example, here's how to tweak a stream so
    that data flowing from left to right trickles in one byte at a time (but
    data flowing from right to left proceeds at full speed)::

        left, right = memory_stream_pair()
        async def trickle():
            # left is a StapledStream, and left.send_stream is a MemorySendStream
            # right is a StapledStream, and right.recv_stream is a MemoryReceiveStream
            while memory_stream_pump(left.send_stream, right.recv_stream, max_byes=1):
                # Pause between each byte
                await trio.sleep(1)
        # Normally this send_all_hook calls memory_stream_pump directly without
        # passing in a max_bytes. We replace it with our custom version:
        left.send_stream.send_all_hook = trickle

    And here's a simple test using our modified stream objects::

        async def sender():
            await left.send_all(b"12345")
            await left.send_eof()

        async def receiver():
            while True:
                data = await right.receive_some(10)
                if data == b"":
                    return
                print(data)

        async with trio.open_nursery() as nursery:
            nursery.spawn(sender)
            nursery.spawn(receiver)

    By default, this will print ``b"12345"`` and then immediately exit; with
    our trickle stream it instead sleeps 1 second, then prints ``b"1"``, then
    sleeps 1 second, then prints ``b"2"``, etc.

    Pro-tip: you can insert sleep calls (like in our example above) to
    manipulate the flow of data across tasks... and then use
    :class:`MockClock` and its :attr:`~MockClock.autojump_threshold`
    functionality to keep your test suite running quickly.

    If you want to stress test a protocol implementation, one nice trick is to
    use the :mod:`random` module (preferably with a fixed seed) to move random
    numbers of bytes at a time, and insert random sleeps in between them. You
    can also set up a custom :attr:`~MemoryReceiveStream.receive_some_hook` if
    you want to manipulate things on the receiving side, and not just the
    sending side.

    """
    return _make_stapled_pair(memory_stream_one_way_pair)


class _LockstepByteQueue:
    def __init__(self):
        self._data = bytearray()
        self._sender_closed = False
        self._receiver_closed = False
        self._receiver_waiting = False
        self._waiters = _core.ParkingLot()
        self._send_lock = _util.UnLock(
            _core.ResourceBusyError, "another task is already sending")
        self._receive_lock = _util.UnLock(
            _core.ResourceBusyError, "another task is already receiving")

    def _something_happened(self):
        self._waiters.unpark_all()

    async def _wait_for(self, fn):
        while not fn():
            await self._waiters.park()

    def close_sender(self):
        # close while send_all is in progress is undefined
        self._sender_closed = True
        self._something_happened()

    def close_receiver(self):
        self._receiver_closed = True
        self._something_happened()

    async def send_all(self, data):
        async with self._send_lock:
            if self._sender_closed:
                raise _streams.ClosedStreamError
            if self._receiver_closed:
                raise _streams.BrokenStreamError
            assert not self._data
            self._data += data
            self._something_happened()
            await self._wait_for(
                lambda: not self._data or self._receiver_closed)
            if self._data and self._receiver_closed:
                raise _streams.BrokenStreamError
            if not self._data:
                return

    async def wait_send_all_might_not_block(self):
        async with self._send_lock:
            if self._sender_closed:
                raise _streams.ClosedStreamError
            if self._receiver_closed:
                return
            await self._wait_for(
                lambda: self._receiver_waiting or self._receiver_closed)

    async def receive_some(self, max_bytes):
        async with self._receive_lock:
            # Argument validation
            max_bytes = operator.index(max_bytes)
            if max_bytes < 1:
                raise ValueError("max_bytes must be >= 1")
            # State validation
            if self._receiver_closed:
                raise _streams.ClosedStreamError
            # Wake wait_send_all_might_not_block and wait for data
            self._receiver_waiting = True
            self._something_happened()
            try:
                await self._wait_for(lambda: self._data or self._sender_closed)
            finally:
                self._receiver_waiting = False
            # Get data, possibly waking send_all
            if self._data:
                got = self._data[:max_bytes]
                del self._data[:max_bytes]
                self._something_happened()
                return got
            else:
                assert self._sender_closed
                return b""


class _LockstepSendStream(_abc.SendStream):
    def __init__(self, lbq):
        self._lbq = lbq

    def forceful_close(self):
        self._lbq.close_sender()

    async def send_all(self, data):
        await self._lbq.send_all(data)

    async def wait_send_all_might_not_block(self):
        await self._lbq.wait_send_all_might_not_block()


class _LockstepReceiveStream(_abc.ReceiveStream):
    def __init__(self, lbq):
        self._lbq = lbq

    def forceful_close(self):
        self._lbq.close_receiver()

    async def receive_some(self, max_bytes):
        return await self._lbq.receive_some(max_bytes)


def lockstep_stream_one_way_pair():
    """Create a connected, pure Python, unidirectional stream where data flows
    in lockstep.

    Returns:
      A tuple
      (:class:`~trio.abc.SendStream`, :class:`~trio.abc.ReceiveStream`).

    This stream has *absolutely no* buffering. Each call to
    :meth:`~trio.abc.SendStream.send_all` will block until all the given data
    has been returned by a call to
    :meth:`~trio.abc.ReceiveStream.receive_some`.

    This can be useful for testing flow control mechanisms in an extreme case,
    or for setting up "clogged" streams to use with
    :func:`check_one_way_stream` and friends.

    """

    lbq = _LockstepByteQueue()
    return _LockstepSendStream(lbq), _LockstepReceiveStream(lbq)


def lockstep_stream_pair():
    """Create a connected, pure-Python, bidirectional stream where data flows
    in lockstep.

    Returns:
      A tuple (:class:`~trio.StapledStream`, :class:`~trio.StapledStream`).

    This is a convenience function that creates two one-way streams using
    :func:`lockstep_stream_one_way_pair`, and then uses
    :class:`~trio.StapledStream` to combine them into a single bidirectional
    stream.

    """
    return _make_stapled_pair(lockstep_stream_one_way_pair)
