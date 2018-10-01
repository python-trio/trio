from collections import deque, OrderedDict
from math import inf

import attr
from outcome import Error, Value

from . import _core
from ._util import aiter_compat
from .abc import AsyncResource

# TODO:
# - docs

# is there a better name for 'clone'? People seem to be having trouble with
# it.

# rename SendChannel/ReceiveChannel to SendHandle/ReceiveHandle?
# eh, maybe not -- SendStream/ReceiveStream don't work like that.

# send or send_object? eh just send is good enough

# implementing this interface on top of a stream is very natural... just
# pickle/unpickle (+ some framing). Actually, even clone() is not bad at
# all... you just need a shared counter of open handles, and then close the
# underlying stream when all SendChannels are closed.

# to think about later:
# - buffer_max=0 default?
# - should we make ReceiveChannel.close() raise BrokenChannelError if data gets
#   lost? This isn't how ReceiveStream works. And it might not be doable for a
#   channel that reaches between processes (e.g. data could be in flight but
#   we don't know it yet)


class EndOfChannel(Exception):
    pass


def open_channel(buffer_max):
    """Open a channel for communicating between tasks.

    A channel is represented by two objects

    Args:
      buffer_max (int or math.inf): The maximum number of items that can be
        buffered in the channel before :meth:`SendChannel.send` blocks.
        Choosing a sensible value here is important to ensure that
        backpressure is communicated promptly and avoid unnecessary latency.
        If in doubt, use 0, which means that sends always block until another
        task calls receive.

    Returns:
      A pair (:class:`SendChannel`, :class:`ReceiveChannel`). Remember: data
      flows from left to right.

    """
    if buffer_max != inf and not isinstance(buffer_max, int):
        raise TypeError("buffer_max must be an integer or math.inf")
    if buffer_max < 0:
        raise ValueError("buffer_max must be >= 0")
    receive_channel = ReceiveChannel(buffer_max)
    send_channel = SendChannel(receive_channel)
    return send_channel, receive_channel


@attr.s(frozen=True)
class ChannelStats:
    buffer_used = attr.ib()
    buffer_max = attr.ib()
    open_send_channels = attr.ib()
    tasks_waiting_send = attr.ib()
    tasks_waiting_receive = attr.ib()


class SendChannel(AsyncResource):
    def __init__(self, receive_channel):
        self._rc = receive_channel
        self._closed = False
        self._tasks = set()
        self._rc._open_send_channels += 1

    def __repr__(self):
        return (
            "<send channel at {:#x}, connected to receive channel at {:#x}>"
            .format(id(self), id(self._rc))
        )

    def statistics(self):
        # XX should we also report statistics specific to this object, like
        # len(self._tasks)?
        return self._rc.statistics()

    @_core.enable_ki_protection
    def send_nowait(self, value):
        """Attempt to send an object into the channel, without blocking.

        Args:
          value (object): The object to send.

        Raises:
          WouldBlock: if the channel is full.
          ClosedResourceError: if this :class:`SendHandle` object has already
              been _closed.
          BrokenChannelError: if the receiving :class:`ReceiveHandle` object
              has already been _closed.

        """
        if self._closed:
            raise _core.ClosedResourceError
        if self._rc._closed:
            raise _core.BrokenResourceError
        if self._rc._receive_tasks:
            assert not self._rc._data
            task, _ = self._rc._receive_tasks.popitem(last=False)
            _core.reschedule(task, Value(value))
        elif len(self._rc._data) < self._rc._capacity:
            self._rc._data.append(value)
        else:
            raise _core.WouldBlock

    @_core.enable_ki_protection
    async def send(self, value):
        """Attempt to send an object into the channel, blocking if necessary.

        Args:
          value (object): The object to send.

        Raises:
          ClosedResourceError: if this :class:`SendChannel` object has already
              been _closed.
          BrokenChannelError: if the receiving :class:`ReceiveHandle` object
              has already been _closed.

        """
        await _core.checkpoint_if_cancelled()
        try:
            self.send_nowait(value)
        except _core.WouldBlock:
            pass
        else:
            await _core.cancel_shielded_checkpoint()
            return

        task = _core.current_task()
        self._tasks.add(task)
        self._rc._send_tasks[task] = value
        task.custom_sleep_data = self

        def abort_fn(_):
            self._tasks.remove(task)
            del self._rc._send_tasks[task]
            return _core.Abort.SUCCEEDED

        await _core.wait_task_rescheduled(abort_fn)

    @_core.enable_ki_protection
    def clone(self):
        """Clone this send channel.

        Raises:
          ClosedResourceError: if this :class:`SendChannel` object has already
              been _closed.
        """
        if self._closed:
            raise _core.ClosedResourceError
        return SendChannel(self._rc)

    @_core.enable_ki_protection
    async def aclose(self):
        if self._closed:
            await _core.checkpoint()
            return
        self._closed = True
        for task in self._tasks:
            _core.reschedule(task, Error(_core.ClosedResourceError()))
            del self._rc._send_tasks[task]
        self._tasks.clear()
        self._rc._open_send_channels -= 1
        if self._rc._open_send_channels == 0:
            assert not self._rc._send_tasks
            for task in self._rc._receive_tasks:
                _core.reschedule(task, Error(EndOfChannel()))
            self._rc._receive_tasks.clear()
        await _core.checkpoint()


@attr.s(cmp=False, hash=False, repr=False)
class ReceiveChannel(AsyncResource):
    _capacity = attr.ib()
    _data = attr.ib(factory=deque)
    _closed = attr.ib(default=False)
    # count of open send channels
    _open_send_channels = attr.ib(default=0)
    # {task: value}
    _send_tasks = attr.ib(factory=OrderedDict)
    # {task: None}
    _receive_tasks = attr.ib(factory=OrderedDict)

    def statistics(self):
        return ChannelStats(
            buffer_used=len(self._data),
            buffer_max=self._capacity,
            open_send_channels=self._open_send_channels,
            tasks_waiting_send=len(self._send_tasks),
            tasks_waiting_receive=len(self._receive_tasks),
        )

    def __repr__(self):
        return "<receive channel at {:#x} with {} senders>".format(
            id(self), self._open_send_channels
        )

    @_core.enable_ki_protection
    def receive_nowait(self):
        if self._closed:
            raise _core.ClosedResourceError
        if self._send_tasks:
            task, value = self._send_tasks.popitem(last=False)
            task.custom_sleep_data._tasks.remove(task)
            _core.reschedule(task)
            self._data.append(value)
            # Fall through
        if self._data:
            return self._data.popleft()
        if not self._open_send_channels:
            raise EndOfChannel
        raise _core.WouldBlock

    @_core.enable_ki_protection
    async def receive(self):
        await _core.checkpoint_if_cancelled()
        try:
            value = self.receive_nowait()
        except _core.WouldBlock:
            pass
        else:
            await _core.cancel_shielded_checkpoint()
            return value

        task = _core.current_task()
        self._receive_tasks[task] = None

        def abort_fn(_):
            del self._receive_tasks[task]
            return _core.Abort.SUCCEEDED

        return await _core.wait_task_rescheduled(abort_fn)

    @_core.enable_ki_protection
    async def aclose(self):
        if self._closed:
            await _core.checkpoint()
            return
        self._closed = True
        for task in self._receive_tasks:
            _core.reschedule(task, Error(_core.ClosedResourceError()))
        self._receive_tasks.clear()
        for task in self._send_tasks:
            task.custom_sleep_data._tasks.remove(task)
            _core.reschedule(task, Error(_core.BrokenResourceError()))
        self._send_tasks.clear()
        # XX: or if we're losing data, maybe we should raise a
        # BrokenChannelError here?
        self._data.clear()
        await _core.checkpoint()

    @aiter_compat
    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.receive()
        except EndOfChannel:
            raise StopAsyncIteration
