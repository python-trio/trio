import pytest

import weakref

from ..testing import wait_all_tasks_blocked, assert_checkpoints

from .. import _core
from .. import _timeouts
from .._timeouts import sleep_forever, move_on_after
from .._sync import *


async def test_Event():
    e = Event()
    assert not e.is_set()
    assert e.statistics().tasks_waiting == 0

    e.set()
    assert e.is_set()
    with assert_checkpoints():
        await e.wait()

    e.clear()
    assert not e.is_set()

    record = []

    async def child():
        record.append("sleeping")
        await e.wait()
        record.append("woken")

    async with _core.open_nursery() as nursery:
        nursery.start_soon(child)
        nursery.start_soon(child)
        await wait_all_tasks_blocked()
        assert record == ["sleeping", "sleeping"]
        assert e.statistics().tasks_waiting == 2
        e.set()
        await wait_all_tasks_blocked()
        assert record == ["sleeping", "sleeping", "woken", "woken"]


async def test_CapacityLimiter():
    with pytest.raises(TypeError):
        CapacityLimiter(1.0)
    with pytest.raises(ValueError):
        CapacityLimiter(-1)
    c = CapacityLimiter(2)
    repr(c)  # smoke test
    assert c.total_tokens == 2
    assert c.borrowed_tokens == 0
    assert c.available_tokens == 2
    with pytest.raises(RuntimeError):
        c.release()
    assert c.borrowed_tokens == 0
    c.acquire_nowait()
    assert c.borrowed_tokens == 1
    assert c.available_tokens == 1

    stats = c.statistics()
    assert stats.borrowed_tokens == 1
    assert stats.total_tokens == 2
    assert stats.borrowers == [_core.current_task()]
    assert stats.tasks_waiting == 0

    # Can't re-acquire when we already have it
    with pytest.raises(RuntimeError):
        c.acquire_nowait()
    assert c.borrowed_tokens == 1
    with assert_checkpoints():
        with pytest.raises(RuntimeError):
            await c.acquire()
    assert c.borrowed_tokens == 1

    # We can acquire on behalf of someone else though
    with assert_checkpoints():
        await c.acquire_on_behalf_of("someone")

    # But then we've run out of capacity
    assert c.borrowed_tokens == 2
    with pytest.raises(_core.WouldBlock):
        c.acquire_on_behalf_of_nowait("third party")

    assert set(c.statistics().borrowers) == {_core.current_task(), "someone"}

    # Until we release one
    c.release_on_behalf_of(_core.current_task())
    assert c.statistics().borrowers == ["someone"]

    c.release_on_behalf_of("someone")
    assert c.borrowed_tokens == 0
    with assert_checkpoints():
        async with c:
            assert c.borrowed_tokens == 1

    async with _core.open_nursery() as nursery:
        await c.acquire_on_behalf_of("value 1")
        await c.acquire_on_behalf_of("value 2")
        nursery.start_soon(c.acquire_on_behalf_of, "value 3")
        await wait_all_tasks_blocked()
        assert c.borrowed_tokens == 2
        assert c.statistics().tasks_waiting == 1
        c.release_on_behalf_of("value 2")
        # Fairness:
        assert c.borrowed_tokens == 2
        with pytest.raises(_core.WouldBlock):
            c.acquire_nowait()

    c.release_on_behalf_of("value 3")
    c.release_on_behalf_of("value 1")


async def test_CapacityLimiter_change_total_tokens():
    c = CapacityLimiter(2)

    with pytest.raises(TypeError):
        c.total_tokens = 1.0

    with pytest.raises(ValueError):
        c.total_tokens = 0

    with pytest.raises(ValueError):
        c.total_tokens = -10

    assert c.total_tokens == 2

    async with _core.open_nursery() as nursery:
        for i in range(5):
            nursery.start_soon(c.acquire_on_behalf_of, i)
            await wait_all_tasks_blocked()
        assert set(c.statistics().borrowers) == {0, 1}
        assert c.statistics().tasks_waiting == 3
        c.total_tokens += 2
        assert set(c.statistics().borrowers) == {0, 1, 2, 3}
        assert c.statistics().tasks_waiting == 1
        c.total_tokens -= 3
        assert c.borrowed_tokens == 4
        assert c.total_tokens == 1
        c.release_on_behalf_of(0)
        c.release_on_behalf_of(1)
        c.release_on_behalf_of(2)
        assert set(c.statistics().borrowers) == {3}
        assert c.statistics().tasks_waiting == 1
        c.release_on_behalf_of(3)
        assert set(c.statistics().borrowers) == {4}
        assert c.statistics().tasks_waiting == 0


# regression test for issue #548
async def test_CapacityLimiter_memleak_548():
    limiter = CapacityLimiter(total_tokens=1)
    await limiter.acquire()

    async with _core.open_nursery() as n:
        n.start_soon(limiter.acquire)
        await wait_all_tasks_blocked()  # give it a chance to run the task
        n.cancel_scope.cancel()

    # if this is 1, the acquire call (despite being killed) is still there in the task, and will
    # leak memory all the while the limiter is active
    assert len(limiter._pending_borrowers) == 0


async def test_Semaphore():
    with pytest.raises(TypeError):
        Semaphore(1.0)
    with pytest.raises(ValueError):
        Semaphore(-1)
    s = Semaphore(1)
    repr(s)  # smoke test
    assert s.value == 1
    assert s.max_value is None
    s.release()
    assert s.value == 2
    assert s.statistics().tasks_waiting == 0
    s.acquire_nowait()
    assert s.value == 1
    with assert_checkpoints():
        await s.acquire()
    assert s.value == 0
    with pytest.raises(_core.WouldBlock):
        s.acquire_nowait()

    s.release()
    assert s.value == 1
    with assert_checkpoints():
        async with s:
            assert s.value == 0
    assert s.value == 1
    s.acquire_nowait()

    record = []

    async def do_acquire(s):
        record.append("started")
        await s.acquire()
        record.append("finished")

    async with _core.open_nursery() as nursery:
        nursery.start_soon(do_acquire, s)
        await wait_all_tasks_blocked()
        assert record == ["started"]
        assert s.value == 0
        s.release()
        # Fairness:
        assert s.value == 0
        with pytest.raises(_core.WouldBlock):
            s.acquire_nowait()
    assert record == ["started", "finished"]


async def test_Semaphore_bounded():
    with pytest.raises(TypeError):
        Semaphore(1, max_value=1.0)
    with pytest.raises(ValueError):
        Semaphore(2, max_value=1)
    bs = Semaphore(1, max_value=1)
    assert bs.max_value == 1
    repr(bs)  # smoke test
    with pytest.raises(ValueError):
        bs.release()
    assert bs.value == 1
    bs.acquire_nowait()
    assert bs.value == 0
    bs.release()
    assert bs.value == 1


@pytest.mark.parametrize(
    "lockcls", [Lock, StrictFIFOLock], ids=lambda fn: fn.__name__
)
async def test_Lock_and_StrictFIFOLock(lockcls):
    l = lockcls()
    assert not l.locked()

    # make sure locks can be weakref'ed (gh-331)
    r = weakref.ref(l)
    assert r() is l

    repr(l)  # smoke test
    # make sure repr uses the right name for subclasses
    assert lockcls.__name__ in repr(l)
    with assert_checkpoints():
        async with l:
            assert l.locked()
            repr(l)  # smoke test (repr branches on locked/unlocked)
    assert not l.locked()
    l.acquire_nowait()
    assert l.locked()
    l.release()
    assert not l.locked()
    with assert_checkpoints():
        await l.acquire()
    assert l.locked()
    l.release()
    assert not l.locked()

    l.acquire_nowait()
    with pytest.raises(RuntimeError):
        # Error out if we already own the lock
        l.acquire_nowait()
    l.release()
    with pytest.raises(RuntimeError):
        # Error out if we don't own the lock
        l.release()

    holder_task = None

    async def holder():
        nonlocal holder_task
        holder_task = _core.current_task()
        async with l:
            await sleep_forever()

    async with _core.open_nursery() as nursery:
        assert not l.locked()
        nursery.start_soon(holder)
        await wait_all_tasks_blocked()
        assert l.locked()
        # WouldBlock if someone else holds the lock
        with pytest.raises(_core.WouldBlock):
            l.acquire_nowait()
        # Can't release a lock someone else holds
        with pytest.raises(RuntimeError):
            l.release()

        statistics = l.statistics()
        print(statistics)
        assert statistics.locked
        assert statistics.owner is holder_task
        assert statistics.tasks_waiting == 0

        nursery.start_soon(holder)
        await wait_all_tasks_blocked()
        statistics = l.statistics()
        print(statistics)
        assert statistics.tasks_waiting == 1

        nursery.cancel_scope.cancel()

    statistics = l.statistics()
    assert not statistics.locked
    assert statistics.owner is None
    assert statistics.tasks_waiting == 0


async def test_Condition():
    with pytest.raises(TypeError):
        Condition(Semaphore(1))
    with pytest.raises(TypeError):
        Condition(StrictFIFOLock)
    l = Lock()
    c = Condition(l)
    assert not l.locked()
    assert not c.locked()
    with assert_checkpoints():
        await c.acquire()
    assert l.locked()
    assert c.locked()

    c = Condition()
    assert not c.locked()
    c.acquire_nowait()
    assert c.locked()
    with pytest.raises(RuntimeError):
        c.acquire_nowait()
    c.release()

    with pytest.raises(RuntimeError):
        # Can't wait without holding the lock
        await c.wait()
    with pytest.raises(RuntimeError):
        # Can't notify without holding the lock
        c.notify()
    with pytest.raises(RuntimeError):
        # Can't notify without holding the lock
        c.notify_all()

    finished_waiters = set()

    async def waiter(i):
        async with c:
            await c.wait()
        finished_waiters.add(i)

    async with _core.open_nursery() as nursery:
        for i in range(3):
            nursery.start_soon(waiter, i)
            await wait_all_tasks_blocked()
        async with c:
            c.notify()
        assert c.locked()
        await wait_all_tasks_blocked()
        assert finished_waiters == {0}
        async with c:
            c.notify_all()
        await wait_all_tasks_blocked()
        assert finished_waiters == {0, 1, 2}

    finished_waiters = set()
    async with _core.open_nursery() as nursery:
        for i in range(3):
            nursery.start_soon(waiter, i)
            await wait_all_tasks_blocked()
        async with c:
            c.notify(2)
            statistics = c.statistics()
            print(statistics)
            assert statistics.tasks_waiting == 1
            assert statistics.lock_statistics.tasks_waiting == 2
        # exiting the context manager hands off the lock to the first task
        assert c.statistics().lock_statistics.tasks_waiting == 1

        await wait_all_tasks_blocked()
        assert finished_waiters == {0, 1}

        async with c:
            c.notify_all()

    # After being cancelled still hold the lock (!)
    # (Note that c.__aexit__ checks that we hold the lock as well)
    with _core.open_cancel_scope() as scope:
        async with c:
            scope.cancel()
            try:
                await c.wait()
            finally:
                assert c.locked()


async def test_Queue():
    with pytest.raises(TypeError):
        Queue(1.0)
    with pytest.raises(ValueError):
        Queue(-1)

    q = Queue(2)
    repr(q)  # smoke test
    assert q.capacity == 2
    assert q.qsize() == 0
    assert q.empty()
    assert not q.full()

    q.put_nowait(1)
    assert q.qsize() == 1
    assert not q.empty()
    assert not q.full()

    with assert_checkpoints():
        await q.put(2)
    assert q.qsize() == 2
    with pytest.raises(_core.WouldBlock):
        q.put_nowait(None)
    assert q.qsize() == 2
    assert not q.empty()
    assert q.full()

    with assert_checkpoints():
        assert await q.get() == 1
    assert q.get_nowait() == 2
    with pytest.raises(_core.WouldBlock):
        q.get_nowait()
    assert q.empty()


async def test_553(autojump_clock):
    q = Queue(1)
    with move_on_after(10) as timeout_scope:
        await q.get()
    assert timeout_scope.cancelled_caught
    await q.put("Test for PR #553")


async def test_Queue_iter():
    q = Queue(1)

    async def producer():
        for i in range(10):
            await q.put(i)
        await q.put(None)

    async def consumer():
        expected = iter(range(10))
        async for item in q:
            if item is None:
                break
            assert item == next(expected)

    async with _core.open_nursery() as nursery:
        nursery.start_soon(producer)
        nursery.start_soon(consumer)


async def test_Queue_statistics():
    q = Queue(3)
    q.put_nowait(1)
    statistics = q.statistics()
    assert statistics.qsize == 1
    assert statistics.capacity == 3
    assert statistics.tasks_waiting_put == 0
    assert statistics.tasks_waiting_get == 0

    async with _core.open_nursery() as nursery:
        q.put_nowait(2)
        q.put_nowait(3)
        assert q.full()
        nursery.start_soon(q.put, 4)
        nursery.start_soon(q.put, 5)
        await wait_all_tasks_blocked()
        statistics = q.statistics()
        assert statistics.qsize == 3
        assert statistics.capacity == 3
        assert statistics.tasks_waiting_put == 2
        assert statistics.tasks_waiting_get == 0
        nursery.cancel_scope.cancel()

    q = Queue(4)
    async with _core.open_nursery() as nursery:
        nursery.start_soon(q.get)
        nursery.start_soon(q.get)
        nursery.start_soon(q.get)
        await wait_all_tasks_blocked()
        statistics = q.statistics()
        assert statistics.qsize == 0
        assert statistics.capacity == 4
        assert statistics.tasks_waiting_put == 0
        assert statistics.tasks_waiting_get == 3
        nursery.cancel_scope.cancel()


async def test_Queue_fairness():

    # We can remove an item we just put, and put an item back in after, if
    # no-one else is waiting.
    q = Queue(1)
    q.put_nowait(1)
    assert q.get_nowait() == 1
    q.put_nowait(2)
    assert q.get_nowait() == 2

    # But if someone else is waiting to get, then they "own" the item we put,
    # so we can't get it (even though we run first):
    q = Queue(1)

    result = None

    async def do_get(q):
        nonlocal result
        result = await q.get()

    async with _core.open_nursery() as nursery:
        nursery.start_soon(do_get, q)
        await wait_all_tasks_blocked()
        q.put_nowait(2)
        with pytest.raises(_core.WouldBlock):
            q.get_nowait()
    assert result == 2

    # And the analogous situation for put: if we free up a space, we can't
    # immediately put something in it if someone is already waiting to do that
    q = Queue(1)
    q.put_nowait(1)
    with pytest.raises(_core.WouldBlock):
        q.put_nowait(None)
    assert q.qsize() == 1
    async with _core.open_nursery() as nursery:
        nursery.start_soon(q.put, 2)
        await wait_all_tasks_blocked()
        assert q.qsize() == 1
        assert q.get_nowait() == 1
        with pytest.raises(_core.WouldBlock):
            q.put_nowait(3)
        assert (await q.get()) == 2


async def test_Queue_unbuffered():
    q = Queue(0)
    assert q.capacity == 0
    assert q.qsize() == 0
    assert q.empty()
    assert q.full()
    with pytest.raises(_core.WouldBlock):
        q.get_nowait()
    with pytest.raises(_core.WouldBlock):
        q.put_nowait(1)

    async def do_put(q, v):
        with assert_checkpoints():
            await q.put(v)

    async with _core.open_nursery() as nursery:
        nursery.start_soon(do_put, q, 1)
        with assert_checkpoints():
            assert await q.get() == 1
    with pytest.raises(_core.WouldBlock):
        q.get_nowait()


# Two ways of implementing a Lock in terms of a Queue. Used to let us put the
# Queue through the generic lock tests.

from .._sync import async_cm


@async_cm
class QueueLock1:
    def __init__(self, capacity):
        self.q = Queue(capacity)
        for _ in range(capacity - 1):
            self.q.put_nowait(None)

    def acquire_nowait(self):
        self.q.put_nowait(None)

    async def acquire(self):
        await self.q.put(None)

    def release(self):
        self.q.get_nowait()


@async_cm
class QueueLock2:
    def __init__(self):
        self.q = Queue(10)
        self.q.put_nowait(None)

    def acquire_nowait(self):
        self.q.get_nowait()

    async def acquire(self):
        await self.q.get()

    def release(self):
        self.q.put_nowait(None)


@async_cm
class QueueLock3:
    def __init__(self):
        self.q = Queue(0)
        # self.acquired is true when one task acquires the lock and
        # only becomes false when it's released and no tasks are
        # waiting to acquire.
        self.acquired = False

    def acquire_nowait(self):
        assert not self.acquired
        self.acquired = True

    async def acquire(self):
        if self.acquired:
            await self.q.put(None)
        else:
            self.acquired = True
            await _core.checkpoint()

    def release(self):
        try:
            self.q.get_nowait()
        except _core.WouldBlock:
            assert self.acquired
            self.acquired = False


lock_factories = [
    lambda: CapacityLimiter(1),
    lambda: Semaphore(1),
    Lock,
    StrictFIFOLock,
    lambda: QueueLock1(10),
    lambda: QueueLock1(1),
    QueueLock2,
    QueueLock3,
]
lock_factory_names = [
    "CapacityLimiter(1)",
    "Semaphore(1)",
    "Lock",
    "StrictFIFOLock",
    "QueueLock1(10)",
    "QueueLock1(1)",
    "QueueLock2",
    "QueueLock3",
]

generic_lock_test = pytest.mark.parametrize(
    "lock_factory", lock_factories, ids=lock_factory_names
)


# Spawn a bunch of workers that take a lock and then yield; make sure that
# only one worker is ever in the critical section at a time.
@generic_lock_test
async def test_generic_lock_exclusion(lock_factory):
    LOOPS = 10
    WORKERS = 5
    in_critical_section = False
    acquires = 0

    async def worker(lock_like):
        nonlocal in_critical_section, acquires
        for _ in range(LOOPS):
            async with lock_like:
                acquires += 1
                assert not in_critical_section
                in_critical_section = True
                await _core.checkpoint()
                await _core.checkpoint()
                assert in_critical_section
                in_critical_section = False

    async with _core.open_nursery() as nursery:
        lock_like = lock_factory()
        for _ in range(WORKERS):
            nursery.start_soon(worker, lock_like)
    assert not in_critical_section
    assert acquires == LOOPS * WORKERS


# Several workers queue on the same lock; make sure they each get it, in
# order.
@generic_lock_test
async def test_generic_lock_fifo_fairness(lock_factory):
    initial_order = []
    record = []
    LOOPS = 5

    async def loopy(name, lock_like):
        # Record the order each task was initially scheduled in
        initial_order.append(name)
        for _ in range(LOOPS):
            async with lock_like:
                record.append(name)

    lock_like = lock_factory()
    async with _core.open_nursery() as nursery:
        nursery.start_soon(loopy, 1, lock_like)
        nursery.start_soon(loopy, 2, lock_like)
        nursery.start_soon(loopy, 3, lock_like)
    # The first three could be in any order due to scheduling randomness,
    # but after that they should repeat in the same order
    for i in range(LOOPS):
        assert record[3 * i:3 * (i + 1)] == initial_order


@generic_lock_test
async def test_generic_lock_acquire_nowait_blocks_acquire(lock_factory):
    lock_like = lock_factory()

    record = []

    async def lock_taker():
        record.append("started")
        async with lock_like:
            pass
        record.append("finished")

    async with _core.open_nursery() as nursery:
        lock_like.acquire_nowait()
        nursery.start_soon(lock_taker)
        await wait_all_tasks_blocked()
        assert record == ["started"]
        lock_like.release()
