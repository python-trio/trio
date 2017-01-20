import attr

from async_generator import async_generator, yield_

from . import _core
from ._util import acontextmanager

__all__ = ["Event"]

@attr.s(slots=True, repr=False, cmp=False, hash=False)
class Event:
    _lot = attr.ib(default=attr.Factory(_core.ParkingLot), init=False)
    _flag = attr.ib(default=False, init=False)

    def statistics(self):
        return self._lot.statistics()

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


class BoundedSemaphore:
    def __init__(self, value):
        self._lot = _core.ParkingLot()
        self._value = self._max_value = value

    @property
    def value(self):
        return self._value

    @property
    def max_value(self):
        return self._max_value

    def statistics(self):
        return self._lot.statistics()

    def acquire_nowait(self):
        if self._value >= 0:
            self._value -= 1
        else:
            raise _core.WouldBlock

    async def acquire(self):
        if self._value >= 0:
            await _core.yield_briefly()
        while self._value == 0:
            await self._lot.park()
        self.acquire_nowait()

    def release(self):
        if self._value == self._max_value:
            raise ValueError("BoundedSemaphore released too many times")
        self._value += 1
        self._lot.unpark(count=1)

    async def __aenter__(self):
        await self.acquire()

    async def __aexit__(self, type, value, traceback):
        self.release()
