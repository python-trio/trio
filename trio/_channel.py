from collections import deque, OrderedDict
from math import inf

import attr
from outcome import Error, Value

from . import _core
from ._util import aiter_compat

# TODO:
# - introspection:
#   - statistics
#   - capacity, usage
#   - repr
# - BrokenResourceError?
# - tests
# - docs
# - should there be a put_back method that inserts an item at the front of the
#   queue, while ignoring length limits? (the idea being that you call this
#   from a task that is also doing get(), and making get() block on put() is
#   a ticket to deadlock city) Example use case: depth-first traversal of a
#   directory tree. (Well... does this work? If you start out 10-wide then you
#   won't converge on a single DFS quickly, or maybe at all... is that still
#   good? do you actually want a priority queue that sorts by depth? maybe
#   that is what you want. Huh.)


class EndOfChannel(Exception):
    pass


class BrokenChannelError(Exception):
    pass


def open_channel(capacity):
    if capacity != inf and not isinstance(capacity, int):
        raise TypeError("capacity must be an integer or math.inf")
    if capacity < 0:
        raise ValueError("capacity must be >= 0")
    buf = ChannelBuf(capacity)
    return PutChannel(buf), GetChannel(buf)


@attr.s(cmp=False, hash=False)
class ChannelBuf:
    capacity = attr.ib()
    data = attr.ib(default=attr.Factory(deque))
    # counts
    put_channels = attr.ib(default=0)
    get_channels = attr.ib(default=0)
    # {task: value}
    put_tasks = attr.ib(default=attr.Factory(OrderedDict))
    # {task: None}
    get_tasks = attr.ib(default=attr.Factory(OrderedDict))


class PutChannel:
    def __init__(self, buf):
        self._buf = buf
        self.closed = False
        self._tasks = set()
        self._buf.put_channels += 1

    @_core.disable_ki_protection
    def put_nowait(self, value):
        if self.closed:
            raise _core.ClosedResourceError
        if not self._buf.get_channels:
            raise BrokenChannelError
        if self._buf.get_tasks:
            assert not self._buf.data
            task, _ = self._buf.get_tasks.popitem(last=False)
            task.custom_sleep_data._tasks.remove(task)
            _core.reschedule(task, Value(value))
        elif len(self._buf.data) < self._buf.capacity:
            self._buf.data.append(value)
        else:
            raise _core.WouldBlock

    @_core.disable_ki_protection
    async def put(self, value):
        await _core.checkpoint_if_cancelled()
        try:
            self.put_nowait(value)
        except _core.WouldBlock:
            pass
        else:
            await _core.cancel_shielded_checkpoint()
            return

        task = _core.current_task()
        self._tasks.add(task)
        self._buf.put_tasks[task] = value
        task.custom_sleep_data = self

        def abort_fn(_):
            self._tasks.remove(task)
            del self._buf.put_tasks[task]
            return _core.Abort.SUCCEEDED

        await _core.wait_task_rescheduled(abort_fn)

    @_core.disable_ki_protection
    def clone(self):
        if self.closed:
            raise _core.ClosedResourceError
        return PutChannel(self._buf)

    @_core.disable_ki_protection
    def close(self):
        if self.closed:
            return
        self.closed = True
        for task in list(self._tasks):
            _core.reschedule(task, Error(ClosedResourceError()))
        self._buf.put_channels -= 1
        if self._buf.put_channels == 0:
            assert not self._buf.put_tasks
            for task in list(self._buf.get_tasks):
                _core.reschedule(task, Error(EndOfChannel()))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class GetChannel:
    def __init__(self, buf):
        self._buf = buf
        self.closed = False
        self._tasks = set()
        self._buf.get_channels += 1

    @_core.disable_ki_protection
    def get_nowait(self):
        if self.closed:
            raise _core.ClosedResourceError
        buf = self._buf
        if buf.put_tasks:
            task, value = buf.put_tasks.popitem(last=False)
            task.custom_sleep_data._tasks.remove(task)
            _core.reschedule(task)
            buf.data.append(value)
            # Fall through
        if buf.data:
            return buf.data.popleft()
        if not buf.put_channels:
            raise EndOfChannel
        raise _core.WouldBlock

    @_core.disable_ki_protection
    async def get(self):
        await _core.checkpoint_if_cancelled()
        try:
            value = self.get_nowait()
        except _core.WouldBlock:
            pass
        else:
            await _core.cancel_shielded_checkpoint()
            return value

        task = _core.current_task()
        self._tasks.add(task)
        self._buf.get_tasks[task] = None
        task.custom_sleep_data = self

        def abort_fn(_):
            self._tasks.remove(task)
            del self._buf.get_tasks[task]
            return _core.Abort.SUCCEEDED

        return await _core.wait_task_rescheduled(abort_fn)

    @_core.disable_ki_protection
    def close(self):
        if self.closed:
            return
        self.closed = True
        for task in list(self._tasks):
            _core.reschedule(task, Error(ClosedResourceError()))
        self._buf.get_channels -= 1
        if self._buf.get_channels == 0:
            assert not self._buf.get_tasks
            for task in list(self._buf.put_tasks):
                _core.reschedule(task, Error(BrokenChannelError()))
            # XX: or if we're losing data, maybe we should raise a
            # BrokenChannelError here?
            self._buf.data.clear()

    @aiter_compat
    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.get()
        except EndOfChannel:
            raise StopAsyncIteration

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
