import pytest

from ... import _core

async def test_UnboundedQueue_basic():
    q = _core.UnboundedQueue()
    q.put_nowait("hi")
    assert await q.get_all() == ["hi"]
    with pytest.raises(_core.WouldBlock):
        q.get_all_nowait()
    q.put_nowait(1)
    q.put_nowait(2)
    q.put_nowait(3)
    assert q.get_all_nowait() == [1, 2, 3]

    assert q.empty()
    assert q.qsize() == 0
    q.put_nowait(None)
    assert not q.empty()
    assert q.qsize() == 1

    stats = q.statistics()
    assert stats.qsize == 1
    assert stats.tasks_waiting_get_all == 0

    # smoke test
    repr(q)

async def test_UnboundedQueue_blocking():
    record = []
    q = _core.UnboundedQueue()
    async def get_all_consumer():
        while True:
            batch = await q.get_all()
            assert batch
            record.append(batch)

    async def aiter_consumer():
        async for batch in q:
            assert batch
            record.append(batch)

    for consumer in (get_all_consumer, aiter_consumer):
        record.clear()
        async with _core.open_nursery() as nursery:
            task = nursery.spawn(consumer)
            await _core.wait_run_loop_idle()
            stats = q.statistics()
            assert stats.qsize == 0
            assert stats.tasks_waiting_get_all == 1
            q.put_nowait(10)
            q.put_nowait(11)
            await _core.wait_run_loop_idle()
            q.put_nowait(12)
            await _core.wait_run_loop_idle()
            assert record == [[10, 11], [12]]
            nursery.cancel_scope.cancel()
