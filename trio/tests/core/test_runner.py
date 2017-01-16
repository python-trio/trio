import pytest

from ... import _core

def test_basic():
    async def trivial(x):
        return x
    assert _core.run(trivial, 8) == 8

    with pytest.raises(TypeError):
        # Missing an argument
        _core.run(trivial)

    with pytest.raises(TypeError):
        # Not an async function
        _core.run(lambda: None)

    async def trivial2(x):
        await _core.yield_briefly()
        return x
    assert _core.run(trivial2, 1) == 1


async def test_basic_spawn_join():
    async def child(x):
        return 2 * x
    task = await _core.spawn(child, 10)
    assert (await task.join()).unwrap() == 20


async def test_basic_interleave():
    async def looper(whoami, record):
        for i in range(3):
            record.append((whoami, i))
            await _core.yield_briefly()

    record = []
    t1 = await _core.spawn(looper, "a", record)
    t2 = await _core.spawn(looper, "b", record)
    await t1.join()
    await t2.join()

    # This test will break if we ever switch away from pure FIFO scheduling,
    # but for now that's what we do, so:
    assert record == [("a", 0), ("b", 0),
                      ("a", 1), ("b", 1),
                      ("a", 2), ("b", 2)]
