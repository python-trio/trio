import operator
from collections import deque

import attr

from . import _core
from ._core._util import aiter_compat

__all__ = ["Event", "BoundedSemaphore", "Queue"]

@attr.s(slots=True, repr=False, cmp=False, hash=False)
class Event:
    _lot = attr.ib(default=attr.Factory(_core.ParkingLot), init=False)
    _flag = attr.ib(default=False, init=False)

    def statistics(self):
        return self._lot.statistics()

    def is_set(self):
        return self._flag

    def set(self):
        self._flag = True
        self._lot.unpark()

    def clear(self):
        self._flag = False

    async def wait(self):
        if self._flag:
            await _core.yield_briefly()
        else:
            await self._lot.park()


class BoundedSemaphore:
    def __init__(self, value):
        self._lot = _core.ParkingLot()
        self._value = self._max_value = value

    @property
    def value(self):
        return self._value

    @property
    def max_value(self):
        return self._max_value

    def statistics(self):
        return self._lot.statistics()

    def acquire_nowait(self):
        if self._value >= 0:
            self._value -= 1
        else:
            raise _core.WouldBlock

    async def acquire(self):
        if self._value >= 0:
            await _core.yield_briefly()
        while self._value == 0:
            await self._lot.park()
        self.acquire_nowait()

    def release(self):
        if self._value == self._max_value:
            raise ValueError("BoundedSemaphore released too many times")
        self._value += 1
        self._lot.unpark(count=1)

    async def __aenter__(self):
        await self.acquire()

    async def __aexit__(self, type, value, traceback):
        self.release()


@attr.s(frozen=True)
class _QueueStats:
    qsize = attr.ib()
    capacity = attr.ib()
    tasks_waiting_put = attr.ib()
    tasks_waiting_get = attr.ib()
    tasks_waiting_join = attr.ib()

# Like queue.Queue, with the notable difference that the capacity argument is
# mandatory.
class Queue:
    def __init__(self, capacity):
        self.capacity = operator.index(capacity)
        self._put_lot = _core.ParkingLot()
        self._get_lot = _core.ParkingLot()
        self._data = deque()
        self._join_lot = _core.ParkingLot()
        self._unprocessed = 0

    def __repr__(self):
        return ("<Queue({}) holding {} items>"
                .format(self.capacity, len(self._data)))

    def statistics(self):
        return _QueueStats(
            qsize=len(self._data),
            capacity=self.capacity,
            tasks_waiting_put=self._put_lot.statistics().tasks_waiting,
            tasks_waiting_get=self._get_lot.statistics().tasks_waiting,
            tasks_waiting_join=self._join_lot.statistics().tasks_waiting)

    def full(self):
        return len(self._data) == self.capacity

    def qsize(self):
        return len(self._data)

    def empty(self):
        return not self._data

    def put_nowait(self, obj):
        if self.full():
            raise _core.WouldBlock
        else:
            self._data.append(obj)
            self._unprocessed += 1
            self._get_lot.unpark(count=1)

    async def put(self, obj):
        # Tricky: if there's room, we must do an artificial wait... but after
        # that there might not be room anymore.
        if not self.full():
            await _core.yield_briefly()
        while self.full():
            await self._put_lot.park()
        self.put_nowait(obj)

    def get_nowait(self):
        if not self._data:
            raise _core.WouldBlock
        self._put_lot.unpark(count=1)
        return self._data.popleft()

    async def get(self):
        # See comment on put()
        if self._data:
            await _core.yield_briefly()
        while not self._data:
            await self._get_lot.park()
        return self.get_nowait()

    def task_done(self):
        self._unprocessed -= 1
        if self._unprocessed == 0:
            self._join_lot.unpark()

    async def join(self):
        if self._unprocessed == 0:
            await _core.yield_briefly()
        else:
            await self._join_lot.park()

    @aiter_compat
    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.get()
