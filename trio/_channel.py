from collections import deque, OrderedDict
from math import inf

import attr
from outcome import Error, Value

from . import _core
from .abc import SendChannel, ReceiveChannel

# rename SendChannel/ReceiveChannel to SendHandle/ReceiveHandle?
# eh, maybe not -- SendStream/ReceiveStream don't work like that.

# send or send_object? eh just send is good enough

# implementing this interface on top of a stream is very natural... just
# pickle/unpickle (+ some framing). Actually, even clone() is not bad at
# all... you just need a shared counter of open handles, and then close the
# underlying stream when all SendChannels are closed.

# to think about later:
# - max_buffer_size=0 default?
# - should we make ReceiveChannel.close() raise BrokenChannelError if data gets
#   lost? This isn't how ReceiveStream works. And it might not be doable for a
#   channel that reaches between processes (e.g. data could be in flight but
#   we don't know it yet). (Well, we could make it raise if it hasn't gotten a
#   clean goodbye message.) OTOH, ReceiveStream has the assumption that you're
#   going to spend significant effort on engineering some protocol on top of
#   it, while Channel is supposed to be useful out-of-the-box.
#   Practically speaking, if a consumer crashes and then its __aexit__
#   replaces the actual exception with BrokenChannelError, that's kind of
#   annoying.
#   But lost messages are bad too... maybe the *sender* aclose() should raise
#   if it lost a message? I guess that has the same issue...
# - should we have a ChannelPair object, instead of returning a tuple?
#   upside: no need to worry about order
#   could have shorthand send/receive methods
#   downside: pretty annoying to type out channel_pair.send_channel like...
#   ever. can't deconstruct on assignment. (Or, well you could by making it
#   implement __iter__, but then that's yet another quirky way to do it.)
# - is their a better/more evocative name for "clone"? People seem to be
#   having trouble with it, but I'm not sure whether it's just because of
#   missing docs.
# - and btw, any better names than Channel (in particular vs. Stream?)
# - should the *_nowait methods be in the ABC? (e.g. doesn't really make sense
#   for something like websockets...)
# - trio.testing.check_channel?


def open_memory_channel(max_buffer_size):
    """Open a channel for passing objects between tasks within a process.

    This channel is lightweight and entirely in-memory; it doesn't involve any
    operating-system resources.

    The channel objects are only closed if you explicitly call
    :meth:`~trio.abc.AsyncResource.aclose` or use ``async with``. In
    particular, they are *not* automatically closed when garbage collected.
    Closing in-memory channel objects is not mandatory, but it's generally a
    good idea, because it helps avoid situations where tasks get stuck
    waiting on a channel when there's no-one on the other side.

    Args:
      max_buffer_size (int or math.inf): The maximum number of items that can
        be buffered in the channel before :meth:`~trio.abc.SendChannel.send`
        blocks. Choosing a sensible value here is important to ensure that
        backpressure is communicated promptly and avoid unnecessary latency;
        see :ref:`channel-buffering` for more details. If in doubt, use 0.

    Returns:
      A pair ``(send_channel, receive_channel)``. If you have
      trouble remembering which order these go in, remember: data
      flows from left → right.

    """
    if max_buffer_size != inf and not isinstance(max_buffer_size, int):
        raise TypeError("max_buffer_size must be an integer or math.inf")
    if max_buffer_size < 0:
        raise ValueError("max_buffer_size must be >= 0")
    state = MemoryChannelState(max_buffer_size)
    return MemorySendChannel(state), MemoryReceiveChannel(state)


@attr.s(frozen=True)
class ChannelStats:
    current_buffer_used = attr.ib()
    max_buffer_size = attr.ib()
    open_send_channels = attr.ib()
    tasks_waiting_send = attr.ib()
    tasks_waiting_receive = attr.ib()


@attr.s
class MemoryChannelState:
    max_buffer_size = attr.ib()
    data = attr.ib(factory=deque)
    # Counts of open endpoints using this state
    open_send_channels = attr.ib(default=0)
    open_receive_channels = attr.ib(default=0)
    # {task: value}
    send_tasks = attr.ib(factory=OrderedDict)
    # {task: None}
    receive_tasks = attr.ib(factory=OrderedDict)

    def statistics(self):
        return ChannelStats(
            current_buffer_used=len(self.data),
            max_buffer_size=self.max_buffer_size,
            open_send_channels=self.open_send_channels,
            tasks_waiting_send=len(self.send_tasks),
            tasks_waiting_receive=len(self.receive_tasks),
        )


@attr.s(cmp=False, repr=False)
class MemorySendChannel(SendChannel):
    _state = attr.ib()
    _closed = attr.ib(default=False)
    # This is just the tasks waiting on *this* object. As compared to
    # self._state.send_tasks, which includes tasks from this object and
    # all clones.
    _tasks = attr.ib(factory=set)

    def __attrs_post_init__(self):
        self._state.open_send_channels += 1

    def __repr__(self):
        return (
            "<send channel at {:#x}, using buffer at {:#x}>".format(
                id(self), id(self._state)
            )
        )

    def statistics(self):
        # XX should we also report statistics specific to this object?
        return self._state.statistics()

    @_core.enable_ki_protection
    def send_nowait(self, value):
        if self._closed:
            raise _core.ClosedResourceError
        if self._state.open_receive_channels == 0:
            raise _core.BrokenResourceError
        if self._state.receive_tasks:
            assert not self._state.data
            task, _ = self._state.receive_tasks.popitem(last=False)
            task.custom_sleep_data._tasks.remove(task)
            _core.reschedule(task, Value(value))
        elif len(self._state.data) < self._state.max_buffer_size:
            self._state.data.append(value)
        else:
            raise _core.WouldBlock

    @_core.enable_ki_protection
    async def send(self, value):
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
        self._state.send_tasks[task] = value
        task.custom_sleep_data = self

        def abort_fn(_):
            self._tasks.remove(task)
            del self._state.send_tasks[task]
            return _core.Abort.SUCCEEDED

        await _core.wait_task_rescheduled(abort_fn)

    @_core.enable_ki_protection
    def clone(self):
        if self._closed:
            raise _core.ClosedResourceError
        return MemorySendChannel(self._state)

    @_core.enable_ki_protection
    async def aclose(self):
        if self._closed:
            await _core.checkpoint()
            return
        self._closed = True
        for task in self._tasks:
            _core.reschedule(task, Error(_core.ClosedResourceError()))
            del self._state.send_tasks[task]
        self._tasks.clear()
        self._state.open_send_channels -= 1
        if self._state.open_send_channels == 0:
            assert not self._state.send_tasks
            for task in self._state.receive_tasks:
                task.custom_sleep_data._tasks.remove(task)
                _core.reschedule(task, Error(_core.EndOfChannel()))
            self._state.receive_tasks.clear()
        await _core.checkpoint()


@attr.s(cmp=False, repr=False)
class MemoryReceiveChannel(ReceiveChannel):
    _state = attr.ib()
    _closed = attr.ib(default=False)
    _tasks = attr.ib(factory=set)

    def __attrs_post_init__(self):
        self._state.open_receive_channels += 1

    def statistics(self):
        return self._state.statistics()

    def __repr__(self):
        return "<receive channel at {:#x}, using buffer at {:#x}>".format(
            id(self), id(self._state)
        )

    @_core.enable_ki_protection
    def receive_nowait(self):
        if self._closed:
            raise _core.ClosedResourceError
        if self._state.send_tasks:
            task, value = self._state.send_tasks.popitem(last=False)
            task.custom_sleep_data._tasks.remove(task)
            _core.reschedule(task)
            self._state.data.append(value)
            # Fall through
        if self._state.data:
            return self._state.data.popleft()
        if not self._state.open_send_channels:
            raise _core.EndOfChannel
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
        self._tasks.add(task)
        self._state.receive_tasks[task] = None
        task.custom_sleep_data = self

        def abort_fn(_):
            self._tasks.remove(task)
            del self._state.receive_tasks[task]
            return _core.Abort.SUCCEEDED

        return await _core.wait_task_rescheduled(abort_fn)

    @_core.enable_ki_protection
    def clone(self):
        if self._closed:
            raise _core.ClosedResourceError
        return MemoryReceiveChannel(self._state)

    @_core.enable_ki_protection
    async def aclose(self):
        if self._closed:
            await _core.checkpoint()
            return
        self._closed = True
        for task in self._tasks:
            _core.reschedule(task, Error(_core.ClosedResourceError()))
            del self._state.receive_tasks[task]
        self._tasks.clear()
        self._state.open_receive_channels -= 1
        if self._state.open_receive_channels == 0:
            assert not self._state.receive_tasks
            for task in self._state.send_tasks:
                task.custom_sleep_data._tasks.remove(task)
                _core.reschedule(task, Error(_core.BrokenResourceError()))
            self._state.send_tasks.clear()
            self._state.data.clear()
        await _core.checkpoint()
