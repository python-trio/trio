from itertools import count
import attr
from sortedcontainers import sorteddict

import .._core
from ._traps import Interrupt, yield_indefinitely

__all__ = ["ParkingLot"]

_counter = count()

class _AllType:
    def __repr__(self):
        return "ParkingLot.ALL"

@attr.s(slots=True)
class ParkingLot:
    _parked = attr.ib(default=attr.Factory(sorteddict))

    ALL = _AllType()

    # XX maybe this should accept a cancel callback?
    async def park(self, status, *, allow_cancel=True):
        idx = next(_counter)
        self._parked[idx] = _core.current_task()
        if allow_cancel:
            def interrupt():
                del self._parked[idx]
                return Interrupt.SUCCEEDED
        else:
            def interrupt():
                return Interrupt.FAILED
        return await yield_indefinitely(status, interrupt)

    def unpark(self, *, count=ParkingLot.ALL, result=_core.Value(None)):
        if count is ParkingLot.ALL:
            count = len(self._parked)
        for _ in range(min(count, len(self._parked))):
            _, task = self._parked.popitem(last=False)
            _core.reschedule(task, result)
