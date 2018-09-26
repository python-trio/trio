import pytest

from ..testing import wait_all_tasks_blocked, assert_checkpoints
import trio
from trio import open_channel, EndOfChannel, BrokenChannelError


async def test_channel():
    with pytest.raises(TypeError):
        open_channel(1.0)
    with pytest.raises(ValueError):
        open_channel(-1)

    p, g = open_channel(2)
    repr(p)  # smoke test
    repr(g)  # smoke test

    p.put_nowait(1)
    with assert_checkpoints():
        await p.put(2)
    with pytest.raises(trio.WouldBlock):
        p.put_nowait(None)

    with assert_checkpoints():
        assert await g.get() == 1
    assert g.get_nowait() == 2
    with pytest.raises(trio.WouldBlock):
        g.get_nowait()

    p.put_nowait("last")
    p.close()
    with pytest.raises(trio.ClosedResourceError):
        await p.put("too late")

    assert g.get_nowait() == "last"
    with pytest.raises(EndOfChannel):
        await g.get()


async def test_553(autojump_clock):
    p, g = open_channel(1)
    with trio.move_on_after(10) as timeout_scope:
        await g.get()
    assert timeout_scope.cancelled_caught
    await p.put("Test for PR #553")


async def test_channel_fan_in():
    async def producer(put_channel, i):
        # We close our handle when we're done with it
        with put_channel:
            for j in range(3 * i, 3 * (i + 1)):
                await put_channel.put(j)

    put_channel, get_channel = open_channel(0)
    async with trio.open_nursery() as nursery:
        # We hand out clones to all the new producers, and then close the
        # original.
        with put_channel:
            for i in range(10):
                nursery.start_soon(producer, put_channel.clone(), i)

        got = []
        async for value in get_channel:
            got.append(value)

        got.sort()
        assert got == list(range(30))


# tests to add:
# - put/get close wakes other puts/gets on close
# - for put, only wakes the ones on the same handle
# - get close -> also wakes puts
#   - and future puts raise
# - all the queue tests, including e.g. fairness tests
# - statistics
