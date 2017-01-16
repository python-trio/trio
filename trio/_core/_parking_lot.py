from itertools import count
import attr
from sortedcontainers import SortedDict

from .. import _core
from ._traps import Abort, yield_indefinitely
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

    async def park(self, *, abort_func=lambda: Abort.SUCCEEDED):
        idx = next(_counter)
        self._parked[idx] = _core.current_task()
        def abort():
            r = abort_func()
            if r is Abort.SUCCEEDED:
                del self._parked[idx]
            return r
        return await yield_indefinitely(abort)

    def unpark(self, *, count=ALL, result=_core.Value(None)):
        if count is ParkingLot.ALL:
            count = len(self._parked)
        for _ in range(min(count, len(self._parked))):
            _, task = self._parked.popitem(last=False)
            _core.reschedule(task, result)
