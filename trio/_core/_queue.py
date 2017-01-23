from collections import deque
from async_generator import async_generator, yield_
import attr

from .. import _core
from ._util import aiter_compat

__all__ = ["Queue"]

class _UnlimitedType:
    def __repr__(self):
        return "Queue.UNLIMITED"

@attr.s(frozen=True)
class _QueueStats:
    waiting_put = attr.ib()
    waiting_get = attr.ib()
    waiting_join = attr.ib()

class Queue:
    UNLIMITED = _UnlimitedType()

    def __init__(self, capacity):
        self.capacity = capacity
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
            waiting_put=self._put_lot.statistics().tasks_waiting,
            tasks_waiting_get=self._get_lot.statistics().tasks_waiting,
            tasks_waiting_join=self._join_lot.statistics().tasks_waiting)

    def full(self):
        if self.capacity is Queue.UNLIMITED:
            return False
        else:
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

    # Useful for e.g. task supervisors, where backpressure is impossible.
    # Basically applying backpressure to the entire program.
    async def get_all(self):
        # See comment on put()
        if self._data:
            await _core.yield_briefly()
        while not self._data:
            await self._get_lot.park()
        data = list(self._data)
        self._data.clear()
        if self.capacity is not Queue.UNLIMITED:
            self._put_lot.unpark(count=self.capacity)
        return data

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

    @async_generator
    async def batched(self):
        while True:
            await yield_(await self.get_all())
