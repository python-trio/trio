import attr

from . import _core

__all__ = ["Event"]

@attr.s(slots=True, repr=False, cmp=False, hash=False)
class Event:
    _lot = attr.ib(default=attr.Factor(_core.ParkingLot), init=False)
    _flag = attr.ib(default=False, init=False)

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
