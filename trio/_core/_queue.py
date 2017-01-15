from collections import deque

from .. import _core

__all__ = ["Queue"]

class _UnlimitedType:
    def __repr__(self):
        return "Queue.UNLIMITED"

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
        if not self.full()
            await _core.yield_briefly()
        while self.full()
            await self._put_lot.park("QUEUE_PUT")
        self.put_nowait(obj)

    def get_nowait(self):
        if not self._data:
            raise WouldBlock
        self._put_lot.unpark(count=1)
        return self._data.popleft()

    async def get(self):
        # See comment on put()
        if self._data:
            await _core.yield_briefly()
        while not self._data:
            await self._get_lot.park("QUEUE_GET")
        return self.get_nowait()

    # Useful for e.g. task supervisors, where backpressure is impossible
    async def get_all(self):
        # See comment on put()
        if self._data:
            await _core.yield_briefly()
        while not self._data:
            await self._get_lot.park("QUEUE_GET")
        data = list(self._data)
        self._data.clear()
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
            await self._join_lot.park("QUEUE_JOIN")
