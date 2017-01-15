from itertools import count
import attr
from sortedcontainers import sorteddict

from .. import _core
from ._traps import Cancel, yield_indefinitely

__all__ = ["ParkingLot"]

_counter = count()

class _AllType:
    def __repr__(self):
        return "ParkingLot.ALL"

@attr.s(slots=True)
class ParkingLot:
    _parked = attr.ib(default=attr.Factory(sorteddict))

    ALL = _AllType()

    async def park(self, *, cancel_func=lambda: Cancel.SUCCEEDED):
        idx = next(_counter)
        self._parked[idx] = _core.current_task()
        def cancel():
            r = cancel_func()
            if r is Cancel.SUCCEEDED:
                del self._parked[idx]
            return r
        return await yield_indefinitely(cancel)

    def unpark(self, *, count=ParkingLot.ALL, result=_core.Value(None)):
        if count is ParkingLot.ALL:
            count = len(self._parked)
        for _ in range(min(count, len(self._parked))):
            _, task = self._parked.popitem(last=False)
            _core.reschedule(task, result)
