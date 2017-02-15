import operator
from collections import deque

import attr

from . import _core
from ._core._util import aiter_compat

__all__ = ["Event", "Semaphore", "Lock", "Condition", "Queue"]

@attr.s(slots=True, repr=False, cmp=False, hash=False)
class Event:
    _lot = attr.ib(default=attr.Factory(_core.ParkingLot), init=False)
    _flag = attr.ib(default=False, init=False)

    def statistics(self):
        return self._lot.statistics()

    def is_set(self):
        return self._flag

    @_core.enable_ki_protection
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


def async_cm(cls):
    @_core.enable_ki_protection
    async def __aenter__(self):
        await self.acquire()
    __aenter__.__qualname__ = cls.__qualname__ + ".__aenter__"
    cls.__aenter__ = __aenter__

    @_core.enable_ki_protection
    async def __aexit__(self, *args):
        self.release()
    __aexit__.__qualname__ = cls.__qualname__ + ".__aexit__"
    cls.__aexit__ = __aexit__
    return cls


@async_cm
class Semaphore:
    def __init__(self, initial_value, *, max_value=None):
        if not isinstance(initial_value, int):
            raise TypeError("initial_value must be an int")
        if initial_value < 0:
            raise ValueError("initial value must be >= 0")
        if max_value is not None:
            if not isinstance(max_value, int):
                raise TypeError("max_value must be None or an int")
            if max_value < initial_value:
                raise ValueError("max_values must be >= initial_value")

        # Invariants:
        # bool(self._lot) implies self._value == 0
        # (or equivalently: self._value > 0 implies not self._lot)
        self._lot = _core.ParkingLot()
        self._value = initial_value
        self._max_value = max_value

    def __repr__(self):
        if self._max_value is None:
            max_value_str = ""
        else:
            max_value_str = ", max_value={}".format(self._max_value)
        return ("<trio.Semaphore({}{}) at {:#x}>"
                .format(self._value, max_value_str, id(self)))

    @property
    def value(self):
        return self._value

    @property
    def max_value(self):
        return self._max_value

    def statistics(self):
        return self._lot.statistics()

    @_core.enable_ki_protection
    def acquire_nowait(self):
        if self._value > 0:
            assert not self._lot
            self._value -= 1
        else:
            raise _core.WouldBlock

    @_core.enable_ki_protection
    async def acquire(self):
        await _core.yield_if_cancelled()
        try:
            self.acquire_nowait()
        except _core.WouldBlock:
            await self._lot.park()
        else:
            await _core.yield_briefly_no_cancel()

    @_core.enable_ki_protection
    def release(self):
        if self._lot:
            assert self._value == 0
            self._lot.unpark(count=1)
        else:
            if self._max_value is not None and self._value == self._max_value:
                raise ValueError("semaphore released too many times")
            self._value += 1


@attr.s(frozen=True)
class _LockStatistics:
    locked = attr.ib()
    owner = attr.ib()
    tasks_waiting = attr.ib()

@async_cm
@attr.s(slots=True, cmp=False, hash=False, repr=False)
class Lock:
    _lot = attr.ib(default=attr.Factory(_core.ParkingLot))
    _owner = attr.ib(default=None)

    def __repr__(self):
        if self.locked():
            s1 = "locked"
            s2 = " with {} waiters".format(len(self._lot))
        else:
            s1 = "unlocked"
            s2 = ""
        return "<{} trio.Lock object at {:#x}{}>".format(s1, id(self), s2)

    def statistics(self):
        return _LockStatistics(
            locked=self.locked(),
            owner=self._owner,
            tasks_waiting=len(self._lot),
        )

    def locked(self):
        return self._owner is not None

    @_core.enable_ki_protection
    def acquire_nowait(self):
        task = _core.current_task()
        if self._owner is task:
            raise RuntimeError("attempt to re-acquire an already held Lock")
        elif self._owner is None and not self._lot:
            # No-one owns it
            self._owner = task
        else:
            raise _core.WouldBlock

    @_core.enable_ki_protection
    async def acquire(self):
        await _core.yield_if_cancelled()
        try:
            self.acquire_nowait()
        except _core.WouldBlock:
            # NOTE: it's important that the contended acquire path is just
            # "_lot.park()", because that's how Condition.wait() acquires the
            # lock as well.
            await self._lot.park()
        else:
            await _core.yield_briefly_no_cancel()

    @_core.enable_ki_protection
    def release(self):
        task = _core.current_task()
        if task is not self._owner:
            raise RuntimeError("can't release a Lock you don't own")
        if self._lot:
            (self._owner,) = self._lot.unpark(count=1)
        else:
            self._owner = None


@attr.s(frozen=True)
class _ConditionStatistics:
    tasks_waiting = attr.ib()
    lock_statistics = attr.ib()

@async_cm
class Condition:
    def __init__(self, lock=None):
        if lock is None:
            lock = Lock()
        if not isinstance(lock, Lock):
            raise TypeError("lock must be a trio.Lock")
        self._lock = lock
        self._lot = _core.ParkingLot()

    def statistics(self):
        return _ConditionStatistics(
            tasks_waiting=len(self._lot),
            lock_statistics=self._lock.statistics(),
        )

    def locked(self):
        return self._lock.locked()

    def acquire_nowait(self):
        return self._lock.acquire_nowait()

    async def acquire(self):
        await self._lock.acquire()

    def release(self):
        self._lock.release()

    async def wait(self):
        if _core.current_task() is not self._lock._owner:
            raise RuntimeError("must hold the lock to wait")
        self.release()
        # NOTE: we go to sleep on this lot, but we'll wake up on
        # self._lock._lot. Fortunately that's all that's required to acquire
        # a Lock.
        try:
            await self._lot.park()
        except _core.Cancelled:
            with _core.open_cancel_scope(shield=True):
                await self.acquire()
            raise

    def notify(self, n=1):
        if _core.current_task() is not self._lock._owner:
            raise RuntimeError("must hold the lock to notify")
        self._lot.repark(self._lock._lot, count=n)

    def notify_all(self):
        if _core.current_task() is not self._lock._owner:
            raise RuntimeError("must hold the lock to notify")
        self._lot.repark(self._lock._lot)


@attr.s(frozen=True)
class _QueueStats:
    qsize = attr.ib()
    capacity = attr.ib()
    tasks_waiting_put = attr.ib()
    tasks_waiting_get = attr.ib()
    tasks_waiting_join = attr.ib()

# Like queue.Queue, with the notable difference that the capacity argument is
# mandatory.
class Queue:
    def __init__(self, capacity):
        if not isinstance(capacity, int):
            raise TypeError("capacity must be an integer")
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        # Invariants:
        #   get_semaphore.value() == len(self._data)
        #   put_semaphore.value() + get_semaphore.value() = capacity
        self.capacity = operator.index(capacity)
        self._put_semaphore = Semaphore(capacity, max_value=capacity)
        self._get_semaphore = Semaphore(0, max_value=capacity)
        self._data = deque()
        self._join_lot = _core.ParkingLot()
        self._unprocessed = 0

    def __repr__(self):
        return ("<Queue({}) at {:#x} holding {} items>"
                .format(self.capacity, id(self), len(self._data)))

    def statistics(self):
        return _QueueStats(
            qsize=len(self._data),
            capacity=self.capacity,
            tasks_waiting_put=self._put_semaphore.statistics().tasks_waiting,
            tasks_waiting_get=self._get_semaphore.statistics().tasks_waiting,
            tasks_waiting_join=self._join_lot.statistics().tasks_waiting)

    def full(self):
        return len(self._data) == self.capacity

    def qsize(self):
        return len(self._data)

    def empty(self):
        return not self._data

    def _put_protected(self, obj):
        self._data.append(obj)
        self._unprocessed += 1
        self._get_semaphore.release()

    @_core.enable_ki_protection
    def put_nowait(self, obj):
        self._put_semaphore.acquire_nowait()
        self._put_protected(obj)

    @_core.enable_ki_protection
    async def put(self, obj):
        await self._put_semaphore.acquire()
        self._put_protected(obj)

    def _get_protected(self):
        self._put_semaphore.release()
        return self._data.popleft()

    @_core.enable_ki_protection
    def get_nowait(self):
        self._get_semaphore.acquire_nowait()
        return self._get_protected()

    @_core.enable_ki_protection
    async def get(self):
        await self._get_semaphore.acquire()
        return self._get_protected()

    @_core.enable_ki_protection
    def task_done(self):
        self._unprocessed -= 1
        if self._unprocessed == 0:
            self._join_lot.unpark()

    async def join(self):
        if self._unprocessed == 0:
            await _core.yield_briefly()
        else:
            await self._join_lot.park()

    @aiter_compat
    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.get()

#
