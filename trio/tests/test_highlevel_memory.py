import pytest

from .. import _core
from ..testing import (
    check_half_closeable_stream, wait_all_tasks_blocked, assert_checkpoints
)
from .._highlevel_memory import *

from .. import testing


async def test_MemoryStream_send_all():
    BIG = 10000000

    a, b = testing.memory_stream_pair()

    # Check a send_all that has to be split into multiple parts (on most
    # platforms... on Windows every send() either succeeds or fails as a
    # whole)
    async def sender():
        data = bytearray(BIG)
        await a.send_all(data)
        # send_all uses memoryviews internally, which temporarily "lock"
        # the object they view. If it doesn't clean them up properly, then
        # some bytearray operations might raise an error afterwards, which
        # would be a pretty weird and annoying side-effect to spring on
        # users. So test that this doesn't happen, by forcing the
        # bytearray's underlying buffer to be realloc'ed:
        data += bytes(BIG)
        # (Note: the above line of code doesn't do a very good job at
        # testing anything, because:
        # - on CPython, the refcount GC generally cleans up memoryviews
        #   for us even if we're sloppy.
        # - on PyPy3, at least as of 5.7.0, the memoryview code and the
        #   bytearray code conspire so that resizing never fails – if
        #   resizing forces the bytearray's internal buffer to move, then
        #   all memoryview references are automagically updated (!!).
        #   See:
        #   https://gist.github.com/njsmith/0ffd38ec05ad8e34004f34a7dc492227
        # But I'm leaving the test here in hopes that if this ever changes
        # and we break our implementation of send_all, then we'll get some
        # early warning...)

    async def receiver():
        # Make sure the sender fills up the kernel buffers and blocks
        await wait_all_tasks_blocked()
        nbytes = 0
        while nbytes < BIG:
            nbytes += len(await b.receive_some(BIG))
        assert nbytes == BIG

    async with _core.open_nursery() as nursery:
        nursery.start_soon(sender)
        nursery.start_soon(receiver)

    # We know that we received BIG bytes of NULs so far. Make sure that
    # was all the data in there.
    await a.send_all(b"e")
    assert await b.receive_some(10) == b"e"
    await a.send_eof()
    assert await b.receive_some(10) == b""


async def fill_stream(s):
    async def sender():
        while True:
            await s.send_all(b"x" * 10000)

    async def waiter(nursery):
        await wait_all_tasks_blocked()
        nursery.cancel_scope.cancel()

    async with _core.open_nursery() as nursery:
        nursery.start_soon(sender)
        nursery.start_soon(waiter, nursery)


async def test_MemoryStream_generic():
    async def stream_maker():
        left, right = testing.memory_stream_pair()
        return left, right

    async def clogged_stream_maker():
        left, right = await stream_maker()
        await fill_stream(left)
        await fill_stream(right)
        return left, right

    await check_half_closeable_stream(stream_maker, clogged_stream_maker)


async def test_MemoryListener():

    async def listener(endpoint, nursery):
        listener = MemoryListener(endpoint)
        # Only wait for one client
        with assert_checkpoints():
            server_stream = await listener.accept()
        assert isinstance(server_stream, MemoryStream)
        # and closes
        with assert_checkpoints():
            await listener.aclose()

        with assert_checkpoints():
            await listener.aclose()

        # Check that we cannot accept after closing
        with assert_checkpoints():
            with pytest.raises(_core.ClosedResourceError):
                await listener.accept()

        await server_stream.aclose()
        nursery.cancel_scope.cancel()

    async def client(endpoint):
        client_stream = await memory_connect(endpoint)
        # client disconnecting immediately
        await client_stream.aclose()

    async with _core.open_nursery() as nursery:
        nursery.start_soon(client, "test_endpoint")
        nursery.start_soon(listener, "test_endpoint", nursery)



async def test_memory_stream_works_when_peer_has_already_closed():
    stream_a, stream_b = testing.memory_stream_pair()
    await stream_b.send_all(b"x")
    await stream_b.aclose()
    assert await stream_a.receive_some(1) == b"x"
    assert await stream_a.receive_some(1) == b""
