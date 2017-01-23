from collections import deque
import attr

from .. import _core
from . import _hazmat
from ._util import aiter_compat

__all__ = ["UnboundedQueue"]

@attr.s(frozen=True)
class _UnboundedQueueStats:
    qsize = attr.ib()
    tasks_waiting_get_all = attr.ib()

@_hazmat
class UnboundedQueue:
    def __init__(self):
        self._lot = _core.ParkingLot()
        self._data = deque()

    def __repr__(self):
        return "<UnboundedQueue holding {} items>".format(len(self._data))

    def statistics(self):
        return _UnboundedQueueStats(
            qsize=len(self._data),
            tasks_waiting_get_all=self._lot.statistics().tasks_waiting)

    def qsize(self):
        return len(self._data)

    def empty(self):
        return not self._data

    def put_nowait(self, obj):
        self._data.append(obj)
        self._lot.unpark(count=1)

    def get_all_nowait(self):
        if not self._data:
            raise _core.WouldBlock
        data = list(self._data)
        self._data.clear()
        return data

    async def get_all(self):
        if self._data:
            await _core.yield_briefly()
        while not self._data:
            await self._lot.park()
        return self.get_all_nowait()

    @aiter_compat
    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.get_all()
