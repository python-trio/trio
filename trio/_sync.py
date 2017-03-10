import operator
from collections import deque

import attr

from . import _core
from ._util import aiter_compat

__all__ = ["Event", "Semaphore", "Lock", "Condition", "Queue"]

@attr.s(slots=True, repr=False, cmp=False, hash=False)
class Event:
    """A waitable boolean value useful for inter-task synchronization,
    inspired by :class:`threading.Event`.

    An event object manages an internal boolean flag, which is initially
    False.

    """

    _lot = attr.ib(default=attr.Factory(_core.ParkingLot), init=False)
    _flag = attr.ib(default=False, init=False)

    def is_set(self):
        """Return the current value of the internal flag.

        """
        return self._flag

    @_core.enable_ki_protection
    def set(self):
        """Set the internal flag value to True, and wake any waiting tasks.

        """
        self._flag = True
        self._lot.unpark_all()

    def clear(self):
        """Set the internal flag value to False.

        """
        self._flag = False

    async def wait(self):
        """Block until the internal flag value becomes True.

        If it's already True, then this method is still a yield point, but
        otherwise returns immediately.

        """
        if self._flag:
            await _core.yield_briefly()
        else:
            await self._lot.park()

    def statistics(self):
        """Return an object containing debugging information.

        Currently the following fields are defined:

        * ``tasks_waiting``: The number of tasks blocked on this event's
          :meth:`wait` method.

        """
        return self._lot.statistics()


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
    """A `semaphore <https://en.wikipedia.org/wiki/Semaphore_(programming)>`__.

    A semaphore holds an integer value, which can be incremented by
    calling :meth:`release` and decremented by calling :meth:`acquire` – but
    the value is never allowed to drop below zero. If the value is zero, then
    :meth:`acquire` will block until someone calls :meth:`release`.

    This is a very flexible synchronization object, but perhaps the most
    common use is to represent a resource with some bounded supply. For
    example, if you want to make sure that there are never more than four
    tasks simultaneously performing some operation, you could do something
    like::

       # Allocate a shared Semaphore object, and somehow distribute it to all
       # your tasks. NB: max_value=4 isn't technically necessary, but can
       # help catch errors.
       sem = trio.Semaphore(4, max_value=4)

       # Then when you perform the operation:
       async with sem:
           await perform_operation()

    This object's interface is similar to, but different from, that of
    :class:`threading.Semaphore`.

    A :class:`Semaphore` object can be used as an async context manager; it
    blocks on entry but not on exit.

    Args:
      initial_value (int): A non-negative integer giving semaphore's initial
        value.
      max_value (int or None): If given, makes this a "bounded" semaphore that
        raises an error if the value is about to exceed the given
        ``max_value``.

    """
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
        """The current value of the semaphore.

        """
        return self._value

    @property
    def max_value(self):
        """The maximum allowed value. May be None to indicate no limit.

        """
        return self._max_value

    @_core.enable_ki_protection
    def acquire_nowait(self):
        """Attempt to decrement the semaphore value, without blocking.

        Raises:
          WouldBlock: if the value is zero.

        """
        if self._value > 0:
            assert not self._lot
            self._value -= 1
        else:
            raise _core.WouldBlock

    @_core.enable_ki_protection
    async def acquire(self):
        """Decrement the semaphore value, blocking if necessary to avoid
        letting it drop below zero.

        """
        await _core.yield_if_cancelled()
        try:
            self.acquire_nowait()
        except _core.WouldBlock:
            await self._lot.park()
        else:
            await _core.yield_briefly_no_cancel()

    @_core.enable_ki_protection
    def release(self):
        """Increment the semaphore value, possibly waking a task blocked in
        :meth:`acquire`.

        Raises:
          ValueError: if incrementing the value would cause it to exceed
              :attr:`max_value`.

        """
        if self._lot:
            assert self._value == 0
            self._lot.unpark(count=1)
        else:
            if self._max_value is not None and self._value == self._max_value:
                raise ValueError("semaphore released too many times")
            self._value += 1

    def statistics(self):
        """Return an object containing debugging information.

        Currently the following fields are defined:

        * ``tasks_waiting``: The number of tasks blocked on this semaphore's
          :meth:`acquire` method.

        """
        return self._lot.statistics()


@attr.s(frozen=True)
class _LockStatistics:
    locked = attr.ib()
    owner = attr.ib()
    tasks_waiting = attr.ib()

@async_cm
@attr.s(slots=True, cmp=False, hash=False, repr=False)
class Lock:
    """A classic `mutex
    <https://en.wikipedia.org/wiki/Lock_(computer_science)>`__.

    This is a non-reentrant, single-owner lock. Unlike
    :class:`threading.Lock`, only the owner of the lock is allowed to release
    it.

    A :class:`Lock` object can be used as an async context manager; it
    blocks on entry but not on exit.

    """

    _lot = attr.ib(default=attr.Factory(_core.ParkingLot), init=False)
    _owner = attr.ib(default=None, init=False)

    def __repr__(self):
        if self.locked():
            s1 = "locked"
            s2 = " with {} waiters".format(len(self._lot))
        else:
            s1 = "unlocked"
            s2 = ""
        return "<{} trio.Lock object at {:#x}{}>".format(s1, id(self), s2)

    def locked(self):
        """Check whether the lock is currently held.

        Returns:
          bool: True if the lock is held, False otherwise.

        """
        return self._owner is not None

    @_core.enable_ki_protection
    def acquire_nowait(self):
        """Attempt to acquire the lock, without blocking.

        Raises:
          WouldBlock: if the lock is held.

        """

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
        """Acquire the lock, blocking if necessary.

        """
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
        """Release the lock.

        Raises:
          RuntimeError: if the calling task does not hold the lock.

        """
        task = _core.current_task()
        if task is not self._owner:
            raise RuntimeError("can't release a Lock you don't own")
        if self._lot:
            (self._owner,) = self._lot.unpark(count=1)
        else:
            self._owner = None

    def statistics(self):
        """Return an object containing debugging information.

        Currently the following fields are defined:

        * ``locked``: boolean indicating whether the lock is held.
        * ``owner``: the :class:`Task` currently holding the lock, or None if
          the lock is not held.
        * ``tasks_waiting``: The number of tasks blocked on this lock's
          :meth:`acquire` method.

        """
        return _LockStatistics(
            locked=self.locked(),
            owner=self._owner,
            tasks_waiting=len(self._lot),
        )


@attr.s(frozen=True)
class _ConditionStatistics:
    tasks_waiting = attr.ib()
    lock_statistics = attr.ib()

@async_cm
class Condition:
    """A classic `condition variable
    <https://en.wikipedia.org/wiki/Monitor_(synchronization)>`__, similar to
    :class:`threading.Condition`.

    A :class:`Condition` object can be used as an async context manager to
    acquire the underlying lock; it blocks on entry but not on exit.

    Args:
      lock (Lock): the lock object to use. If given, must be a
          :class:`trio.Lock`. If None, a new :class:`Lock` will be allocated
          and used.

    """
    def __init__(self, lock=None):
        if lock is None:
            lock = Lock()
        if not isinstance(lock, Lock):
            raise TypeError("lock must be a trio.Lock")
        self._lock = lock
        self._lot = _core.ParkingLot()

    def locked(self):
        """Check whether the underlying lock is currently held.

        Returns:
          bool: True if the lock is held, False otherwise.

        """
        return self._lock.locked()

    def acquire_nowait(self):
        """Attempt to acquire the underlying lock, without blocking.

        Raises:
          WouldBlock: if the lock is currently held.

        """
        return self._lock.acquire_nowait()

    async def acquire(self):
        """Acquire the underlying lock, blocking if necessary.

        """
        await self._lock.acquire()

    def release(self):
        """Release the underlying lock.

        """
        self._lock.release()

    @_core.enable_ki_protection
    async def wait(self):
        """Wait for another thread to call :meth:`notify` or
        :meth:`notify_all`.

        When calling this method, you must hold the lock. It releases the lock
        while waiting, and then re-acquires it before waking up.

        There is a subtlety with how this method interacts with cancellation:
        when cancelled it will block to re-acquire the lock before raising
        :exc:`Cancelled`. This may cause cancellation to be less prompt than
        expected. The advantage is that it makes code like this work::

           async with condition:
               await condition.wait()

        If we didn't re-acquire the lock before waking up, and :meth:`wait`
        were cancelled here, then we'd crash in ``condition.__aexit__`` when
        we tried to release the lock we no longer held.

        Raises:
          RuntimeError: if the calling task does not hold the lock.

        """
        if _core.current_task() is not self._lock._owner:
            raise RuntimeError("must hold the lock to wait")
        self.release()
        # NOTE: we go to sleep on self._lot, but we'll wake up on
        # self._lock._lot. That's all that's required to acquire a Lock.
        try:
            await self._lot.park()
        except:
            with _core.open_cancel_scope(shield=True):
                await self.acquire()
            raise

    def notify(self, n=1):
        """Wake one or more tasks that are blocked in :meth:`wait`.

        Args:
          n (int): The number of tasks to wake.

        Raises:
          RuntimeError: if the calling task does not hold the lock.

        """
        if _core.current_task() is not self._lock._owner:
            raise RuntimeError("must hold the lock to notify")
        self._lot.repark(self._lock._lot, count=n)

    def notify_all(self):
        """Wake all tasks that are currently blocked in :meth:`wait`.

        Raises:
          RuntimeError: if the calling task does not hold the lock.

        """
        if _core.current_task() is not self._lock._owner:
            raise RuntimeError("must hold the lock to notify")
        self._lot.repark_all(self._lock._lot)

    def statistics(self):
        """Return an object containing debugging information.

        Currently the following fields are defined:

        * ``tasks_waiting``: The number of tasks blocked on this condition's
          :meth:`wait` method.
        * ``lock_statistics``: The result of calling the underlying
          :class:`Lock`\s  :meth:`~Lock.statistics` method.

        """
        return _ConditionStatistics(
            tasks_waiting=len(self._lot),
            lock_statistics=self._lock.statistics(),
        )


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
    """A bounded queue suitable for inter-task communication.

    This class is generally modelled after :class:`queue.Queue`, but with the
    major difference that it is always bounded. For an unbounded queue, see
    :class:`trio.UnboundedQueue`.

    A :class:`Queue` object can be used as an asynchronous iterator, that
    dequeues objects one at a time. I.e., these two loops are equivalent::

       async for obj in queue:
           ...

       while True:
           obj = await queue.get()
           ...

    Args:
      capacity (int): The maximum number of items allowed in the queue before
          :meth:`put` blocks. Choosing a sensible value here is important to
          ensure that backpressure is communicated promptly and avoid
          unnecessary latency. If in doubt, use 1.

    """

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

    def qsize(self):
        """Returns the number of items currently in the queue.

        There is some subtlety to interpreting this method's return value: see
        `issue #63 <https://github.com/python-trio/trio/issues/63>`__.

        """
        return len(self._data)

    def full(self):
        """Returns True if the queue is at capacity, False otherwise.

        There is some subtlety to interpreting this method's return value: see
        `issue #63 <https://github.com/python-trio/trio/issues/63>`__.

        """
        return len(self._data) == self.capacity

    def empty(self):
        """Returns True if the queue is empty, False otherwise.

        There is some subtlety to interpreting this method's return value: see
        `issue #63 <https://github.com/python-trio/trio/issues/63>`__.

        """
        return not self._data

    def _put_protected(self, obj):
        self._data.append(obj)
        self._unprocessed += 1
        self._get_semaphore.release()

    @_core.enable_ki_protection
    def put_nowait(self, obj):
        """Attempt to put an object into the queue, without blocking.

        Args:
          obj (object): The object to enqueue.

        Raises:
          WouldBlock: if the queue is full.

        """
        self._put_semaphore.acquire_nowait()
        self._put_protected(obj)

    @_core.enable_ki_protection
    async def put(self, obj):
        """Put an object into the queue, blocking if necessary.

        Args:
          obj (object): The object to enqueue.

        """
        await self._put_semaphore.acquire()
        self._put_protected(obj)

    def _get_protected(self):
        self._put_semaphore.release()
        return self._data.popleft()

    @_core.enable_ki_protection
    def get_nowait(self):
        """Attempt to get an object from the queue, without blocking.

        Returns:
          object: The dequeued object.

        Raises:
          WouldBlock: if the queue is empty.

        """
        self._get_semaphore.acquire_nowait()
        return self._get_protected()

    @_core.enable_ki_protection
    async def get(self):
        """Get an object from the queue, blocking is necessary.

        Returns:
          object: The dequeued object.

        """
        await self._get_semaphore.acquire()
        return self._get_protected()

    @_core.enable_ki_protection
    def task_done(self):
        """Decrement the count of unfinished work.

        Each :class:`Queue` object keeps a count of unfinished work, which
        starts at zero and is incremented after each successful
        :meth:`put`. This method decrements it again. When the count reaches
        zero, any tasks blocked in :meth:`join` are woken.

        """
        self._unprocessed -= 1
        if self._unprocessed == 0:
            self._join_lot.unpark_all()

    async def join(self):
        """Block until the count of unfinished work reaches zero.

        See :meth:`task_done` for details.

        """
        if self._unprocessed == 0:
            await _core.yield_briefly()
        else:
            await self._join_lot.park()

    @aiter_compat
    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.get()

    def statistics(self):
        """Returns an object containing debugging information.

        Currently the following fields are defined:

        * ``qsize``: The number of items currently in the queue.
        * ``capacity``: The maximum number of items the queue can hold.
        * ``tasks_waiting_put``: The number of tasks blocked on this queue's
          :meth:`put` method.
        * ``tasks_waiting_get``: The number of tasks blocked on this queue's
          :meth:`get` method.
        * ``tasks_waiting_join``: The number of tasks blocked on this queue's
          :meth:`join` method.

        """
        return _QueueStats(
            qsize=len(self._data),
            capacity=self.capacity,
            tasks_waiting_put=self._put_semaphore.statistics().tasks_waiting,
            tasks_waiting_get=self._get_semaphore.statistics().tasks_waiting,
            tasks_waiting_join=self._join_lot.statistics().tasks_waiting)
