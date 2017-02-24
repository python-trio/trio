from collections import deque
import attr

from .. import _core
from . import _hazmat
from .._util import aiter_compat

__all__ = ["UnboundedQueue"]

@attr.s(frozen=True)
class _UnboundedQueueStats:
    qsize = attr.ib()
    tasks_waiting = attr.ib()

class UnboundedQueue:
    def __init__(self):
        self._lot = _core.ParkingLot()
        self._data = []
        # used to allow handoff from put to the first task in the lot
        self._can_get = False

    def __repr__(self):
        return "<UnboundedQueue holding {} items>".format(len(self._data))

    def statistics(self):
        return _UnboundedQueueStats(
            qsize=len(self._data),
            tasks_waiting=self._lot.statistics().tasks_waiting)

    def qsize(self):
        return len(self._data)

    def empty(self):
        return not self._data

    @_core.enable_ki_protection
    def put_nowait(self, obj):
        if not self._data:
            assert not self._can_get
            if self._lot:
                self._lot.unpark(count=1)
            else:
                self._can_get = True
        self._data.append(obj)

    def _get_all_protected(self):
        data = self._data.copy()
        self._data.clear()
        self._can_get = False
        return data

    def get_all_nowait(self):
        if not self._can_get:
            raise _core.WouldBlock
        return self._get_all_protected()

    async def get_all(self):
        if not self._can_get:
            await self._lot.park()
        return self._get_all_protected()

    @aiter_compat
    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.get_all()
