# This doesn't really belong in _core, except it's used by Queue, which is
# used by KqueueIOManager...

from itertools import count
import attr
from sortedcontainers import SortedDict

from .. import _core
from . import _hazmat

__all__ = ["ParkingLot"]

_counter = count()

class _AllType:
    def __repr__(self):
        return "ParkingLot.ALL"

@attr.s(frozen=True)
class _ParkingLotStatistics:
    tasks_waiting = attr.ib()

@_hazmat
@attr.s(slots=True, cmp=False, hash=False)
class ParkingLot:
    _parked = attr.ib(default=attr.Factory(SortedDict))

    ALL = _AllType()

    def statistics(self):
        return _ParkingLotStatistics(tasks_waiting=len(self._parked))

    @_core.enable_ki_protection
    async def park(self):
        idx = next(_counter)
        self._parked[idx] = _core.current_task()
        def abort():
            del self._parked[idx]
            return _core.Abort.SUCCEEDED
        return await _core.yield_indefinitely(abort)

    @_core.enable_ki_protection
    def unpark(self, *, count=ALL, result=_core.Value(None)):
        if count is ParkingLot.ALL:
            count = len(self._parked)
        for _ in range(min(count, len(self._parked))):
            _, task = self._parked.popitem(last=False)
            _core.reschedule(task, result)
