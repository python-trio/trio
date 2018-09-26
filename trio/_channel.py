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
# - tests
# - docs


class EndOfChannel(Exception):
    pass


class BrokenChannelError(Exception):
    pass


def open_channel(capacity):
    if capacity != inf and not isinstance(capacity, int):
        raise TypeError("capacity must be an integer or math.inf")
    if capacity < 0:
        raise ValueError("capacity must be >= 0")
    get_channel = GetChannel(capacity)
    put_channel = PutChannel(get_channel)
    return put_channel, get_channel


class PutChannel:
    def __init__(self, get_channel):
        self._gc = get_channel
        self.closed = False
        self._tasks = set()
        self._gc._open_put_channels += 1

    @_core.enable_ki_protection
    def put_nowait(self, value):
        if self.closed:
            raise _core.ClosedResourceError
        if self._gc.closed:
            raise BrokenChannelError
        if self._gc._get_tasks:
            assert not self._gc._data
            task, _ = self._gc._get_tasks.popitem(last=False)
            _core.reschedule(task, Value(value))
        elif len(self._gc._data) < self._gc._capacity:
            self._gc._data.append(value)
        else:
            raise _core.WouldBlock

    @_core.enable_ki_protection
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
        self._gc._put_tasks[task] = value
        task.custom_sleep_data = self

        def abort_fn(_):
            self._tasks.remove(task)
            del self._gc._put_tasks[task]
            return _core.Abort.SUCCEEDED

        await _core.wait_task_rescheduled(abort_fn)

    @_core.enable_ki_protection
    def clone(self):
        if self.closed:
            raise _core.ClosedResourceError
        return PutChannel(self._gc)

    @_core.enable_ki_protection
    def close(self):
        if self.closed:
            return
        self.closed = True
        for task in self._tasks:
            _core.reschedule(task, Error(ClosedResourceError()))
        self._tasks.clear()
        self._gc._open_put_channels -= 1
        if self._gc._open_put_channels == 0:
            assert not self._gc._put_tasks
            for task in self._gc._get_tasks:
                _core.reschedule(task, Error(EndOfChannel()))
            self._gc._get_tasks.clear()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@attr.s(cmp=False, hash=False, repr=False)
class GetChannel:
    _capacity = attr.ib()
    _data = attr.ib(default=attr.Factory(deque))
    closed = attr.ib(default=False)
    # count of open put channels
    _open_put_channels = attr.ib(default=0)
    # {task: value}
    _put_tasks = attr.ib(default=attr.Factory(OrderedDict))
    # {task: None}
    _get_tasks = attr.ib(default=attr.Factory(OrderedDict))

    @_core.enable_ki_protection
    def get_nowait(self):
        if self.closed:
            raise _core.ClosedResourceError
        if self._put_tasks:
            task, value = self._put_tasks.popitem(last=False)
            task.custom_sleep_data._tasks.remove(task)
            _core.reschedule(task)
            self._data.append(value)
            # Fall through
        if self._data:
            return self._data.popleft()
        if not self._open_put_channels:
            raise EndOfChannel
        raise _core.WouldBlock

    @_core.enable_ki_protection
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
        self._get_tasks[task] = None

        def abort_fn(_):
            del self._get_tasks[task]
            return _core.Abort.SUCCEEDED

        return await _core.wait_task_rescheduled(abort_fn)

    @_core.enable_ki_protection
    def close(self):
        if self.closed:
            return
        self.closed = True
        for task in self._get_tasks:
            _core.reschedule(task, Error(ClosedResourceError()))
        self._get_tasks.clear()
        for task in self._put_tasks:
            _core.reschedule(task, Error(BrokenChannelError()))
        self._put_tasks.clear()
        # XX: or if we're losing data, maybe we should raise a
        # BrokenChannelError here?
        self._data.clear()

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
