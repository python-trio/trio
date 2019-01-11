import pytest

from ..testing import wait_all_tasks_blocked, assert_checkpoints
import trio
from trio import open_memory_channel, EndOfChannel


async def test_channel():
    with pytest.raises(TypeError):
        open_memory_channel(1.0)
    with pytest.raises(ValueError):
        open_memory_channel(-1)

    s, r = open_memory_channel(2)
    repr(s)  # smoke test
    repr(r)  # smoke test

    s.send_nowait(1)
    with assert_checkpoints():
        await s.send(2)
    with pytest.raises(trio.WouldBlock):
        s.send_nowait(None)

    with assert_checkpoints():
        assert await r.receive() == 1
    assert r.receive_nowait() == 2
    with pytest.raises(trio.WouldBlock):
        r.receive_nowait()

    s.send_nowait("last")
    await s.aclose()
    with pytest.raises(trio.ClosedResourceError):
        await s.send("too late")
    with pytest.raises(trio.ClosedResourceError):
        s.send_nowait("too late")
    with pytest.raises(trio.ClosedResourceError):
        s.clone()
    await s.aclose()

    assert r.receive_nowait() == "last"
    with pytest.raises(EndOfChannel):
        await r.receive()
    await r.aclose()
    with pytest.raises(trio.ClosedResourceError):
        await r.receive()
    with pytest.raises(trio.ClosedResourceError):
        await r.receive_nowait()
    await r.aclose()


async def test_553(autojump_clock):
    s, r = open_memory_channel(1)
    with trio.move_on_after(10) as timeout_scope:
        await r.receive()
    assert timeout_scope.cancelled_caught
    await s.send("Test for PR #553")


async def test_channel_multiple_producers():
    async def producer(send_channel, i):
        # We close our handle when we're done with it
        async with send_channel:
            for j in range(3 * i, 3 * (i + 1)):
                await send_channel.send(j)

    send_channel, receive_channel = open_memory_channel(0)
    async with trio.open_nursery() as nursery:
        # We hand out clones to all the new producers, and then close the
        # original.
        async with send_channel:
            for i in range(10):
                nursery.start_soon(producer, send_channel.clone(), i)

        got = []
        async for value in receive_channel:
            got.append(value)

        got.sort()
        assert got == list(range(30))


async def test_channel_multiple_consumers():
    successful_receivers = set()
    received = []

    async def consumer(receive_channel, i):
        async for value in receive_channel:
            successful_receivers.add(i)
            received.append(value)

    async with trio.open_nursery() as nursery:
        send_channel, receive_channel = trio.open_memory_channel(1)
        async with send_channel:
            for i in range(5):
                nursery.start_soon(consumer, receive_channel, i)
            await wait_all_tasks_blocked()
            for i in range(10):
                await send_channel.send(i)

    assert successful_receivers == set(range(5))
    assert len(received) == 10
    assert set(received) == set(range(10))


async def test_close_basics():
    async def send_block(s, expect):
        with pytest.raises(expect):
            await s.send(None)

    # closing send -> other send gets ClosedResourceError
    s, r = open_memory_channel(0)
    async with trio.open_nursery() as nursery:
        nursery.start_soon(send_block, s, trio.ClosedResourceError)
        await wait_all_tasks_blocked()
        await s.aclose()

    # and it's persistent
    with pytest.raises(trio.ClosedResourceError):
        s.send_nowait(None)
    with pytest.raises(trio.ClosedResourceError):
        await s.send(None)

    # and receive gets EndOfChannel
    with pytest.raises(EndOfChannel):
        r.receive_nowait()
    with pytest.raises(EndOfChannel):
        await r.receive()

    # closing receive -> send gets BrokenResourceError
    s, r = open_memory_channel(0)
    async with trio.open_nursery() as nursery:
        nursery.start_soon(send_block, s, trio.BrokenResourceError)
        await wait_all_tasks_blocked()
        await r.aclose()

    # and it's persistent
    with pytest.raises(trio.BrokenResourceError):
        s.send_nowait(None)
    with pytest.raises(trio.BrokenResourceError):
        await s.send(None)

    # closing receive -> other receive gets ClosedResourceError
    async def receive_block(r):
        with pytest.raises(trio.ClosedResourceError):
            await r.receive()

    s, r = open_memory_channel(0)
    async with trio.open_nursery() as nursery:
        nursery.start_soon(receive_block, r)
        await wait_all_tasks_blocked()
        await r.aclose()

    # and it's persistent
    with pytest.raises(trio.ClosedResourceError):
        r.receive_nowait()
    with pytest.raises(trio.ClosedResourceError):
        await r.receive()


async def test_receive_channel_clone_and_close():
    s, r = open_memory_channel(10)

    r2 = r.clone()
    r3 = r.clone()

    s.send_nowait(None)
    await r.aclose()
    async with r2:
        pass

    with pytest.raises(trio.ClosedResourceError):
        r.clone()

    with pytest.raises(trio.ClosedResourceError):
        r2.clone()

    # Can still send, r3 is still open
    s.send_nowait(None)

    await r3.aclose()

    # But now the receiver is really closed
    with pytest.raises(trio.BrokenResourceError):
        s.send_nowait(None)


async def test_close_multiple_send_handles():
    # With multiple send handles, closing one handle only wakes senders on
    # that handle, but others can continue just fine
    s1, r = open_memory_channel(0)
    s2 = s1.clone()

    async def send_will_close():
        with pytest.raises(trio.ClosedResourceError):
            await s1.send("nope")

    async def send_will_succeed():
        await s2.send("ok")

    async with trio.open_nursery() as nursery:
        nursery.start_soon(send_will_close)
        nursery.start_soon(send_will_succeed)
        await wait_all_tasks_blocked()
        await s1.aclose()
        assert await r.receive() == "ok"


async def test_close_multiple_receive_handles():
    # With multiple receive handles, closing one handle only wakes receivers on
    # that handle, but others can continue just fine
    s, r1 = open_memory_channel(0)
    r2 = r1.clone()

    async def receive_will_close():
        with pytest.raises(trio.ClosedResourceError):
            await r1.receive()

    async def receive_will_succeed():
        assert await r2.receive() == "ok"

    async with trio.open_nursery() as nursery:
        nursery.start_soon(receive_will_close)
        nursery.start_soon(receive_will_succeed)
        await wait_all_tasks_blocked()
        await r1.aclose()
        await s.send("ok")


async def test_inf_capacity():
    s, r = open_memory_channel(float("inf"))

    # It's accepted, and we can send all day without blocking
    async with s:
        for i in range(10):
            s.send_nowait(i)

    got = []
    async for i in r:
        got.append(i)
    assert got == list(range(10))


async def test_statistics():
    s, r = open_memory_channel(2)

    assert s.statistics() == r.statistics()
    stats = s.statistics()
    assert stats.current_buffer_used == 0
    assert stats.max_buffer_size == 2
    assert stats.open_send_channels == 1
    assert stats.open_receive_channels == 1
    assert stats.tasks_waiting_send == 0
    assert stats.tasks_waiting_receive == 0

    s.send_nowait(None)
    assert s.statistics().current_buffer_used == 1

    s2 = s.clone()
    assert s.statistics().open_send_channels == 2
    await s.aclose()
    assert s2.statistics().open_send_channels == 1

    r2 = r.clone()
    assert s2.statistics().open_receive_channels == 2
    await r2.aclose()
    assert s2.statistics().open_receive_channels == 1

    async with trio.open_nursery() as nursery:
        s2.send_nowait(None)  # fill up the buffer
        assert s.statistics().current_buffer_used == 2
        nursery.start_soon(s2.send, None)
        nursery.start_soon(s2.send, None)
        await wait_all_tasks_blocked()
        assert s.statistics().tasks_waiting_send == 2
        nursery.cancel_scope.cancel()
    assert s.statistics().tasks_waiting_send == 0

    # empty out the buffer again
    try:
        while True:
            r.receive_nowait()
    except trio.WouldBlock:
        pass

    async with trio.open_nursery() as nursery:
        nursery.start_soon(r.receive)
        await wait_all_tasks_blocked()
        assert s.statistics().tasks_waiting_receive == 1
        nursery.cancel_scope.cancel()
    assert s.statistics().tasks_waiting_receive == 0


async def test_channel_fairness():

    # We can remove an item we just sent, and send an item back in after, if
    # no-one else is waiting.
    s, r = open_memory_channel(1)
    s.send_nowait(1)
    assert r.receive_nowait() == 1
    s.send_nowait(2)
    assert r.receive_nowait() == 2

    # But if someone else is waiting to receive, then they "own" the item we
    # send, so we can't receive it (even though we run first):

    result = None

    async def do_receive(r):
        nonlocal result
        result = await r.receive()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(do_receive, r)
        await wait_all_tasks_blocked()
        s.send_nowait(2)
        with pytest.raises(trio.WouldBlock):
            r.receive_nowait()
    assert result == 2

    # And the analogous situation for send: if we free up a space, we can't
    # immediately send something in it if someone is already waiting to do
    # that
    s, r = open_memory_channel(1)
    s.send_nowait(1)
    with pytest.raises(trio.WouldBlock):
        s.send_nowait(None)
    async with trio.open_nursery() as nursery:
        nursery.start_soon(s.send, 2)
        await wait_all_tasks_blocked()
        assert r.receive_nowait() == 1
        with pytest.raises(trio.WouldBlock):
            s.send_nowait(3)
        assert (await r.receive()) == 2


async def test_unbuffered():
    s, r = open_memory_channel(0)
    with pytest.raises(trio.WouldBlock):
        r.receive_nowait()
    with pytest.raises(trio.WouldBlock):
        s.send_nowait(1)

    async def do_send(s, v):
        with assert_checkpoints():
            await s.send(v)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(do_send, s, 1)
        with assert_checkpoints():
            assert await r.receive() == 1
    with pytest.raises(trio.WouldBlock):
        r.receive_nowait()


async def test_poison():
    s, r = open_memory_channel(0)

    # Tasks blocked when the poisoning occurs get woken up immediately
    async def expect_poison(fn, *args):
        with pytest.raises(trio.BrokenResourceError) as exc_info:
            await fn(*args)
        assert str(exc_info.value).startswith("channel is poisoned:")

    async def run_sync(fn, *args):
        fn(*args)

    async with r.clone() as r2, trio.open_nursery() as nursery:
        nursery.start_soon(expect_poison, r.receive)
        nursery.start_soon(expect_poison, r.receive)
        nursery.start_soon(expect_poison, r2.receive)
        nursery.start_soon(expect_poison, r2.receive)
        await wait_all_tasks_blocked()
        with assert_checkpoints():
            await s.poison("hi")

    # Further sending and receiving fails fast
    await expect_poison(s.send, "foo")
    await expect_poison(run_sync, s.send_nowait, "bar")
    await expect_poison(run_sync, r.receive_nowait)

    # Can poison multiple times and all are reported
    # Can poison while cancelled
    with trio.open_cancel_scope() as scope:
        scope.cancel()
        with assert_checkpoints():
            await s.poison("there")
    assert scope.cancelled_caught

    with pytest.raises(trio.BrokenResourceError) as exc_info:
        await r.receive()
    assert str(exc_info.value) == "channel is poisoned: ['hi', 'there']"

    # Clones can be made, but they're poisoned too
    async with s.clone() as s2, r.clone() as r2:
        await expect_poison(s2.send, "baz")
        await expect_poison(r2.receive)

    # Can close a poisoned channel
    with assert_checkpoints():
        await s.aclose()

    # Receivers are poisoned even if all senders are closed
    assert r.statistics().open_send_channels == 0
    await expect_poison(r.receive)

    # Can't poison a closed channel
    with assert_checkpoints(), pytest.raises(trio.ClosedResourceError):
        await s.poison("again")

    # Poisoning attempted after closure does not affect the state
    with pytest.raises(trio.BrokenResourceError) as exc_info:
        await r.receive()
    assert str(exc_info.value) == "channel is poisoned: ['hi', 'there']"

    # Test that poisoning wakes up senders too
    s, r = open_memory_channel(1)
    s.send_nowait("one")

    async with s.clone() as s2, trio.open_nursery() as nursery:
        nursery.start_soon(expect_poison, s.send, "two")
        nursery.start_soon(expect_poison, s2.send, "three")
        await wait_all_tasks_blocked()
        with assert_checkpoints():
            await s.poison("hi")

    # Receivers can receive values that were sent before the poisoning
    assert r.receive_nowait() == "one"
    await expect_poison(run_sync, r.receive_nowait)

    # Test exception propagation
    s, r = open_memory_channel(0)

    async def poison_when_fails(send_channel, fn, *args):
        with pytest.raises(Exception):
            async with send_channel.propagate_errors():
                await fn(*args)

    async def raise_(exc_type):
        raise exc_type

    async with trio.open_nursery() as nursery:
        nursery.start_soon(poison_when_fails, s, raise_, KeyError)

        with pytest.raises(trio.BrokenResourceError) as exc_info:
            await r.receive()
        assert type(exc_info.value.__cause__) is KeyError

    import traceback
    frames = traceback.extract_tb(exc_info.value.__cause__.__traceback__)
    functions = [function for _, _, function, _ in frames]
    assert functions[-2:] == ['poison_when_fails', 'raise_']

    with pytest.raises(trio.ClosedResourceError):
        await s.send("yo")

    # ... with multiple exceptions
    s, r = open_memory_channel(0)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(poison_when_fails, s, raise_, KeyError)
        nursery.start_soon(poison_when_fails, s, raise_, ValueError)

    with pytest.raises(trio.BrokenResourceError) as exc_info:
        await r.receive()
    assert type(exc_info.value.__cause__) is trio.MultiError
    assert {KeyError, ValueError} == {
        type(exc)
        for exc in exc_info.value.__cause__.exceptions
    }

    # Exceptions that were caused by the poisoning shouldn't be reported
    # as having caused it
    s, r = open_memory_channel(0)
    s2 = s.clone()
    await poison_when_fails(s, raise_, trio.BrokenResourceError)
    await poison_when_fails(s2, s2.send, "yo")
    with pytest.raises(trio.BrokenResourceError) as exc_info:
        await r.receive()
    assert type(exc_info.value.__cause__) is trio.BrokenResourceError
    assert "poison" not in str(exc_info.value.__cause__)
