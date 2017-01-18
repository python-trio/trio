from .. import sleep
from .. import _core
from ..testing import *

async def test_busy_wait_for():
    record = []
    register = [0]
    async def child(childname, values):
        for value in values:
            await busy_wait_for(lambda: register[0] == value)
            record.append("{}{}".format(childname, value))
            register[0] += 1

    await _core.spawn(child, "a", [0, 3, 4])
    await _core.spawn(child, "b", [1, 2])
    c = await _core.spawn(child, "c", [5])
    await c.join()

    assert record == ["a0", "b1", "b2", "a3", "a4", "c5"]


async def test_quiesce():
    record = []
    async def busy_bee():
        for _ in range(10):
            await _core.yield_briefly()
        record.append("busy bee exhausted")

    async def waiting_for_bee_to_leave():
        await quiesce()
        record.append("quiet at last!")

    t1 = await _core.spawn(busy_bee)
    # Having two waiters makes it trickier, since if they spawned independent
    # quiesce loops then they'd each make the other look awake.  (XX
    # alternatively, tag tasks as being quiesce loops or not, and then we
    # could tag busy_wait_for as well? this would be easier with support for
    # task-locals...)
    t2 = await _core.spawn(waiting_for_bee_to_leave)
    t3 = await _core.spawn(waiting_for_bee_to_leave)
    (await t1.join()).unwrap()
    (await t2.join()).unwrap()
    (await t3.join()).unwrap()


async def test_quiesce_with_timeouts(mock_clock):
    record = []
    async def timeout_task():
        record.append("tt start")
        await sleep(5)
        record.append("tt finished")
    t = await _core.spawn(timeout_task)
    await quiesce()
    assert record == ["tt start"]
    mock_clock.advance(10)
    await quiesce()
    assert record == ["tt start", "tt finished"]
