import threading
from functools import wraps, partial
from contextlib import contextmanager
import inspect
from collections import defaultdict
import time
from math import inf
import random

import attr
from async_generator import async_generator, yield_

from . import _util
from . import _core
from . import Event as _Event, sleep as _sleep, StapledStream as _StapledStream
from . import abc as _abc

__all__ = [
    "wait_all_tasks_blocked", "trio_test", "MockClock",
    "assert_yields", "assert_no_yields", "Sequencer",
    "MemorySendStream", "MemoryRecvStream", "memory_stream_pump",
    "memory_stream_one_way", "memory_stream_two_way",
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
        self._both = both

    async def __aenter__(self):
        return self._both

    async def __aexit__(self, *args):
        try:
            await self._both[0].graceful_close()
        finally:
            await self._both[1].graceful_close()


@contextmanager
def _assert_raises(exc):
    try:
        yield
    except exc:
        ok = True
    else:
        ok = False
    assert ok, "expected exception: {}".format(exc)


async def check_one_way_stream(stream_maker, clogged_stream_maker):
    async with _CloseBoth(stream_maker()) as (s, r):
        assert isinstance(s, SendStream)
        assert isinstance(r, ReceiveStream)

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
            nursery.spawn(checked_receive, 1, b"x")

        async def send_empty_then_y():
            # Streams should tolerate sending b"" without giving it any
            # special meaning.
            await do_send_all(b"")
            await do_send_all(b"y")

        async with _core.open_nursery() as nursery:
            nursery.spawn(send_empty_then_y)
            nursery.spawn(checked_receive, 1, b"y")

        ### Checking various argument types

        # send_all accepts bytearray and memoryview
        async with _core.open_nursery() as nursery:
            nursery.spawn(do_send_all, bytearray(b"1"))
            nursery.spawn(checked_receive_1, b"1")

        async with _core.open_nursery() as nursery:
            nursery.spawn(do_send_all, memoryview(b"2"))
            nursery.spawn(checked_receive_1, b"2")

        # max_bytes must be a positive integer
        for bad in [-1, 0, 1.5]:
            with _assert_raises((TypeError, ValueError)):
                await r.receive_some(bad)

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
            nursery.spawn(simple_check_wait_send_all_might_not_block)
            nursery.spawn(do_receive_some, 1)

        # closing the r side
        do_graceful_close(r)

        # ...leads to BrokenStreamError on the s side (eventually)
        with _assert_raises(_core.BrokenStreamError):
            while True:
                await do_send_all(b"x" * 100)

        # once detected, the stream stays broken
        with _assert_raises(_core.BrokenStreamError):
            await do_send_all(b"x" * 100)

        # r closed -> ClosedStreamError on the receive side
        with _assert_raises(_core.ClosedStreamError):
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
        with _assert_raises(_core.ClosedStreamError):
            await do_send_all(b"x" * 100)

        # and again, repeated closing is fine
        s.forceful_close()
        with assert_yields():
            await do_graceful_close(s)
        s.forceful_close()

    async with _CloseBoth(stream_maker()) as (s, r):
        async with _core.open_nursery() as nursery:
            nursery.spawn(do_send_all, b"x")
            nursery.spawn(checked_receive, 1, b"x")

        # receiver get b"" after the sender does a graceful_close
        async with _core.open_nursery() as nursery:
            nursery.spawn(s.graceful_close)
            nursery.spawn(checked_receive, 1, b"")

    # using forceful_close also makes things closed
    async with _CloseBoth(stream_maker()) as (s, r):
        r.forceful_close()

        with _assert_raises(_core.BrokenStreamError):
            while True:
                await do_send_all(b"x" * 100)

        with _assert_raises(_core.ClosedStreamError):
            await do_receive_some(4096)

    async with _CloseBoth(stream_maker()) as (s, r):
        s.forceful_close()

        with _assert_raises(_core.ClosedStreamError):
            await do_send_all(b"123")

        # after the sender does a forceful close, the receiver might either
        # get BrokenStreamError or a clean b""; either is OK. Not OK would be
        # if it freezes, or returns data.
        try:
            await checked_receive_1(b"")
        except _core.BrokenStreamError:
            pass

    # cancelled graceful_close still closes
    async with _CloseBoth(stream_maker()) as (s, r):
        with _core.open_cancel_scope() as scope:
            scope.cancel()
            await r.graceful_close()

        with _core.open_cancel_scope() as scope:
            scope.cancel()
            await s.graceful_close()

        with _assert_raises(_core.ClosedStreamError):
            do_send_all(b"123")

        with _assert_raises(_core.ClosedStreamError):
            do_receive_some(4096)

    # check wait_send_all_might_not_block, if we can
    if clogged_stream_maker is not None:
        async with _CloseBoth(clogged_stream_maker()) as (s, r):
            record = []

            async def waiter():
                record.append("waiter sleeping")
                with assert_yields():
                    await s.wait_send_all_might_not_block()
                record.append("waiter wokeup")

            async def receiver():
                # give wait_send_all_might_not_block a chance to block
                await wait_all_tasks_blocked()
                record.append("receiver starting")
                while "waiter wokeup" not in record:
                    await r.receive_some(16834)

            async with _core.open_nursery() as nursery:
                nursery.spawn(waiter)
                await wait_all_tasks_blocked()
                nursery.spawn(receiver)

            assert record == [
                "waiter sleeping",
                "receiver starting",
                "waiter wokeup",
            ]

        async with _CloseBoth(clogged_stream_maker()) as (s, r):
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

        async with _CloseBoth(clogged_stream_maker()) as (s, r):
            # send_all and send_all blocked simultaneously should also raise
            # (but again this might destroy the stream)
            with _assert_raises(_core.ResourceBusyError):
                async with _core.open_nursery() as nursery:
                    nursery.spawn(s.send_all, b"123")
                    nursery.spawn(s.send_all, b"123")


async def check_two_way_stream(stream_maker, clogged_stream_maker):
    check_one_way_stream(stream_maker, clogged_stream_maker)
    flipped_stream_maker = lambda: stream_maker()[::-1]
    if clogged_stream_maker is not None:
        flipped_clogged_stream_maker = lambda: clogged_stream_maker()[::-1]
    else:
        flipped_clogged_stream_maker = None
    check_one_way_stream(flipped_stream_maker, flipped_clogged_stream_maker)

    async with _CloseBoth(stream_maker()) as (s1, s2):
        assert isinstance(s1, Stream)
        assert isinstance(s2, Stream)

        # Duplex can be a bit tricky, might as well check it as well
        DUPLEX_TEST_SIZE = 2 ** 20
        CHUNK_SIZE_MAX = 2 ** 14

        r = random.Random(0)
        i = r.getrandbits(256 ** DUPLEX_TEST_SIZE)
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
                chunk = await r.receive_some(r.randint(1, CHUNK_SIZE_MAX))
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


async def check_half_closeable_stream(stream_maker):
    check_two_way_stream(stream_maker)

    async with _CloseBoth(stream_maker()) as (s1, s2):
        assert isinstance(s1, HalfCloseableStream)
        assert isinstance(s2, HalfCloseableStream)


################################################################
# In-memory streams
################################################################

# XX it might be useful to move this to _sync.py and make it public?
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
            # Same error raised by trying to send on a closed socket
            raise BrokenPipeError("virtual connection closed")
        self._data += data
        self._lot.unpark_all()

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
            if not self._closed and not self._data:
                raise _core.WouldBlock
            return self._get_impl(max_bytes)

    async def get(self, max_bytes=None):
        async with self._fetch_lock:
            if not self._closed and not self._data:
                await self._lot.park()
            return self._get_impl(max_bytes)


class MemorySendStream(_abc.SendStream):
    """An in-memory :class:`~trio.abc.SendStream`.

    Args:
      sendall_hook: An async function, or None. Called from
          :meth:`sendall`. Can do whatever you like.
      wait_sendall_might_not_block_hook: An async function, or None. Called
          from :meth:`wait_sendall_might_not_block`. Can do whatever you
          like.
      close_hook: A synchronous function, or None. Called from
          :meth:`forceful_close`. Can do whatever you like.

    .. attribute:: sendall_hook
                   wait_sendall_might_not_block_hook
                   close_hook

       All of these hooks are also exposed as attributes on the object, and
       you can change them at any time.

    """
    def __init__(self,
                 sendall_hook=None,
                 wait_sendall_might_not_block_hook=None,
                 close_hook=None):
        self._lock = _util.UnLock(
            _core.ResourceBusyError, "another task is using this stream")
        self._outgoing = _UnboundedByteQueue()
        self.sendall_hook = sendall_hook
        self.wait_sendall_might_not_block_hook = wait_sendall_might_not_block_hook
        self.close_hook = close_hook

    async def sendall(self, data):
        """Places the given data into the object's internal buffer, and then
        calls the :attr:`sendall_hook` (if any).

        """
        # The lock itself is a checkpoint, but then we also yield inside the
        # lock to give ourselves a chance to detect buggy user code that calls
        # this twice at the same time.
        async with self._lock:
            await _core.yield_briefly()
            self._outgoing.put(data)
            if self.sendall_hook is not None:
                await self.sendall_hook()

    async def wait_sendall_might_not_block(self):
        """Calls the :attr:`wait_sendall_might_not_block_hook` (if any), and
        then returns immediately.

        """
        # The lock itself is a checkpoint, but then we also yield inside the
        # lock to give ourselves a chance to detect buggy user code that calls
        # this twice at the same time.
        async with self._lock:
            await _core.yield_briefly()
            if self.wait_sendall_might_not_block_hook is not None:
                await self.wait_sendall_might_not_block_hook()

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


class MemoryRecvStream(_abc.RecvStream):
    """An in-memory :class:`~trio.abc.RecvStream`.

    Args:
      recv_hook: An async function, or None. Called from
          :meth:`recv`. Can do whatever you like.

    .. attribute:: recv_hook

       The :attr:`recv_hook` is also exposed as an attribute on the object,
       and you can change it at any time.

    """
    def __init__(self, recv_hook=None):
        self._lock = _util.UnLock(
            _core.ResourceBusyError, "another task is using this stream")
        self._incoming = _UnboundedByteQueue()
        self.recv_hook = recv_hook

    async def recv(self, max_bytes):
        """Calls the :attr:`recv_hook` (if any), and then retrieves data from
        the internal buffer, blocking if necessary.

        """
        # The lock itself is a checkpoint, but then we also yield inside the
        # lock to give ourselves a chance to detect buggy user code that calls
        # this twice at the same time.
        async with self._lock:
            await _core.yield_briefly()
            if max_bytes is None:
                raise TypeError("max_bytes must not be None")
            if self.recv_hook is not None:
                await self.recv_hook()
            return await self._incoming.get(max_bytes)

    def forceful_close(self):
        """Discards any pending data from the internal buffer, and marks this
        stream as closed.

        """
        # discard any pending data
        try:
            self._incoming.get_nowait()
        except _core.WouldBlock:
            pass
        self._incoming.close()

    def put_data(self, data):
        """Appends the given data to the internal buffer.

        """
        self._incoming.put(data)

    def put_eof(self):
        """Adds an end-of-file marker to the internal buffer; the stream will
        be closed after any previous data is retrieved.

        """
        self._incoming.close()


def memory_stream_pump(
        memory_send_stream, memory_recv_stream, *, max_bytes=None):
    """Take data out of the given :class:`MemorySendStream`'s internal buffer,
    and put it into the given :class:`MemoryRecvStream`'s internal buffer.

    Args:
      memory_send_stream (MemorySendStream): The stream to get data from.
      memory_recv_stream (MemoryRecvStream): The stream to put data into.
      max_bytes (int or None): The maximum amount of data to transfer in this
          call, or None to transfer all available data.

    Returns:
      True if it successfully transferred some data, or False if there was no
      data to transfer.

    This is used to implement of :func:`memory_stream_one_way` and
    :func:`memory_stream_two_way`; see the latter's docstring for an example
    of how you might use it yourself.

    """
    try:
        data = memory_send_stream.get_data_nowait(max_bytes)
    except _core.WouldBlock:
        return False
    if not data:
        memory_recv_stream.put_eof()
    else:
        memory_recv_stream.put_data(data)
    return True


def memory_stream_one_way():
    """Create a connected, in-memory, unidirectional stream.

    You can think of this as being a pure-Python, trio-streamsified version of
    :func:`os.pipe`.

    Returns:
      A tuple (:class:`MemorySendStream`, :class:`MemoryRecvStream`), where
      the :class:`MemorySendStream` has its hooks set up so that it calls
      :func:`memory_stream_pump` from its
      :attr:`~MemorySendStream.sendall_hook` and
      :attr:`~MemorySendStream.close_hook`.

    The end result is that data automatically flows from the
    :class:`MemorySendStream` to the :class:`MemoryRecvStream`. But you're
    also free to rearrange things however you like. For example, you can
    temporarily set the :attr:`~MemorySendStream.sendall_hook` to None if you
    want to simulate a stall in data transmission. Or see
    :func:`memory_stream_two_way` for a more elaborate example.

    """
    send_stream = MemorySendStream()
    recv_stream = MemoryRecvStream()
    def pump_from_send_stream_to_recv_stream():
        memory_stream_pump(send_stream, recv_stream)
    async def async_pump_from_send_stream_to_recv_stream():
        pump_from_send_stream_to_recv_stream()
    send_stream.sendall_hook = async_pump_from_send_stream_to_recv_stream
    send_stream.close_hook = pump_from_send_stream_to_recv_stream
    return send_stream, recv_stream


def memory_stream_two_way():
    """Create a connected, in-memory, bidirectional stream.

    This is a convenience function that creates two one-way streams using
    :func:`memory_stream_one_way`, and then uses :class:`~trio.StapledStream`
    to combine them into a single bidirectional stream.

    This is like a pure-Python, trio-streamsified version of
    :func:`socket.socketpair`.

    Returns:
      A pair of :class:`~trio.StapledStream` objects that are connected so
      that data automatically flows from one to the other in both directions.

    See :class:`~trio.StapledStream` and :func:`memory_stream_one_way` for the
    full details of how this is wired up; all the pieces involved are public
    APIs, so you can adjust to suit the requirements of your tests. For
    example, here's how to tweak a stream so that data flowing from left to
    right trickles in one byte at a time (but data flowing from right to left
    proceeds at full speed)::

        left, right = memory_stream_two_way()
        async def trickle():
            # left is a StapledStream, and left.send_stream is a MemorySendStream
            # right is a StapledStream, and right.recv_stream is a MemoryRecvStream
            while memory_stream_pump(left.send_stream, right.recv_stream, max_byes=1):
                # Pause between each byte
                await trio.sleep(1)
        # Replace the regular call to memory_stream_pump
        left.send_stream.sendall_hook = trickle

        # Will take 5 seconds
        await left.sendall(b"12345")

        assert await right.recv(5) == b"12345"

    Pro-tip: you can insert sleep calls (like in our example above) to
    manipulate the flow of data between your tasks... and then use
    :class:`MockClock` and its :attr:`~MockClock.autojump_threshold`
    functionality to keep your test suite running quickly.

    If you want to stress test a protocol implementation, one nice trick is to
    use the :mod:`random` module (preferably with a fixed seed) to move random
    numbers of bytes at a time, and insert random sleeps in between them. You
    can also set up a custom :attr:`~MemoryRecvStream.recv_hook` if you want
    to manipulate things on the receiving side, and not just the sending
    side.

    """
    pipe1_send, pipe1_recv = memory_stream_one_way()
    pipe2_send, pipe2_recv = memory_stream_one_way()
    stream1 = _StapledStream(pipe1_send, pipe2_recv)
    stream2 = _StapledStream(pipe2_send, pipe1_recv)
    return stream1, stream2
