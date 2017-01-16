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

@_hazmat
@attr.s(slots=True)
class ParkingLot:
    _parked = attr.ib(default=attr.Factory(SortedDict))

    ALL = _AllType()

    async def park(self, *, abort_func=lambda: _core.Abort.SUCCEEDED):
        idx = next(_counter)
        self._parked[idx] = _core.current_task()
        def abort():
            r = abort_func()
            if r is _core.Abort.SUCCEEDED:
                del self._parked[idx]
            return r
        return await _core.yield_indefinitely(abort)

    def unpark(self, *, count=ALL, result=_core.Value(None)):
        if count is ParkingLot.ALL:
            count = len(self._parked)
        for _ in range(min(count, len(self._parked))):
            _, task = self._parked.popitem(last=False)
            _core.reschedule(task, result)
