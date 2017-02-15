import pytest

from ..testing import wait_run_loop_idle, assert_yields

from .. import _core
from .._timeouts import sleep_forever
from .._sync import *

async def test_Event():
    e = Event()
    assert not e.is_set()
    assert e.statistics().tasks_waiting == 0

    e.set()
    assert e.is_set()
    await e.wait()

    e.clear()
    assert not e.is_set()

    record = []
    async def child():
        record.append("sleeping")
        await e.wait()
        record.append("woken")

    async with _core.open_nursery() as nursery:
        t1 = nursery.spawn(child)
        t2 = nursery.spawn(child)
        await wait_run_loop_idle()
        assert record == ["sleeping", "sleeping"]
        assert e.statistics().tasks_waiting == 2
        e.set()
        await wait_run_loop_idle()
        assert record == ["sleeping", "sleeping", "woken", "woken"]


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
    with assert_yields():
        await s.acquire()
    assert s.value == 0
    with pytest.raises(_core.WouldBlock):
        s.acquire_nowait()

    s.release()
    assert s.value == 1
    async with s:
        assert s.value == 0
    assert s.value == 1
    s.acquire_nowait()

    async with _core.open_nursery() as nursery:
        t = nursery.spawn(s.acquire)
        await wait_run_loop_idle()
        assert t.result is None
        assert s.value == 0
        s.release()
        # Fairness:
        assert s.value == 0
        with pytest.raises(_core.WouldBlock):
            s.acquire_nowait()
        await t.wait()


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


async def test_Lock():
    l = Lock()
    assert not l.locked()
    repr(l)  # smoke test
    async with l:
        assert l.locked()
        repr(l)  # smoke test (repr branches on locked/unlocked)
    assert not l.locked()
    l.acquire_nowait()
    assert l.locked()
    l.release()
    assert not l.locked()
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

    async def holder():
        async with l:
            await sleep_forever()

    async with _core.open_nursery() as nursery:
        assert not l.locked()
        t = nursery.spawn(holder)
        await wait_run_loop_idle()
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
        assert statistics.owner is t
        assert statistics.tasks_waiting == 0

        nursery.spawn(holder)
        await wait_run_loop_idle()
        statistics = l.statistics()
        print(statistics)
        assert statistics.tasks_waiting == 1

        nursery.cancel_scope.cancel()

    statistics = l.statistics()
    assert not statistics.locked
    assert statistics.owner is None
    assert statistics.tasks_waiting == 0

generic_lock_test = pytest.mark.parametrize(
    "lock_factory", [lambda: Semaphore(1), Lock], ids=["Semaphore(1)", "Lock"])

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
                await _core.yield_briefly()
                await _core.yield_briefly()
                assert in_critical_section
                in_critical_section = False

    async with _core.open_nursery() as nursery:
        lock_like = lock_factory()
        for _ in range(WORKERS):
            nursery.spawn(worker, lock_like)
    assert not in_critical_section
    assert acquires == LOOPS * WORKERS

# Several workers queue on the same lock; make sure they each get it, in
# order.
@generic_lock_test
async def test_generic_lock_fairness(lock_factory):
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
        nursery.spawn(loopy, 1, lock_like)
        nursery.spawn(loopy, 2, lock_like)
        nursery.spawn(loopy, 3, lock_like)
    # The first three could be in any order due to scheduling randomness,
    # but after that they should repeat in the same order
    for i in range(LOOPS):
        assert record[3*i : 3*(i + 1)] == initial_order


async def test_Condition():
    with pytest.raises(TypeError):
        Condition(Semaphore(1))
    l = Lock()
    c = Condition(l)
    assert not l.locked()
    assert not c.locked()
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

    async def waiter():
        async with c:
            await c.wait()

    async with _core.open_nursery() as nursery:
        w = []
        for _ in range(3):
            w.append(nursery.spawn(waiter))
            await wait_run_loop_idle()
        async with c:
            c.notify()
        assert c.locked()
        await wait_run_loop_idle()
        assert w[0].result is not None
        assert w[1].result is w[2].result is None
        async with c:
            c.notify_all()
        await wait_run_loop_idle()
        assert w[1].result is not None
        assert w[2].result is not None

    async with _core.open_nursery() as nursery:
        w = []
        for _ in range(3):
            w.append(nursery.spawn(waiter))
            await wait_run_loop_idle()
        async with c:
            c.notify(2)
            statistics = c.statistics()
            print(statistics)
            assert statistics.tasks_waiting == 1
            assert statistics.lock_statistics.tasks_waiting == 2
        # exiting the context manager hands off the lock to the first task
        assert c.statistics().lock_statistics.tasks_waiting == 1

        await wait_run_loop_idle()
        assert w[0].result is not None
        assert w[1].result is not None
        assert w[2].result is None

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
    async with _core.open_nursery() as nursery:
        t = nursery.spawn(q.get)
        await wait_run_loop_idle()
        q.put_nowait(2)
        with pytest.raises(_core.WouldBlock):
            q.get_nowait()
    assert t.result.unwrap() == 2

    # And the analogous situation for put: if we free up a space, we can't
    # immediately put something in it if someone is already waiting to do that
    q = Queue(1)
    q.put_nowait(1)
    with pytest.raises(_core.WouldBlock):
        q.put_nowait(None)
    assert q.qsize() == 1
    async with _core.open_nursery() as nursery:
        t = nursery.spawn(q.put, 2)
        await wait_run_loop_idle()
        assert q.qsize() == 1
        assert q.get_nowait() == 1
        with pytest.raises(_core.WouldBlock):
            q.put_nowait(3)
        assert (await q.get()) == 2
