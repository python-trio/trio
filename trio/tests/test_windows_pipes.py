import errno
import select

import os
import sys
import pytest

from .._core.tests.tutil import gc_collect_harder
from .. import _core, move_on_after
from ..testing import wait_all_tasks_blocked, check_one_way_stream

if sys.platform == "win32":
    from .._windows_pipes import (
        PipeSendStream,
        PipeReceiveStream,
        PipeSendChannel,
        PipeReceiveChannel,
        DEFAULT_RECEIVE_SIZE,
    )
    from .._core._windows_cffi import (
        _handle,
        kernel32,
        PipeModes,
        get_pipe_state,
    )
    from asyncio.windows_utils import pipe
    from multiprocessing.connection import Pipe
else:
    pytestmark = pytest.mark.skip(reason="windows only")
    pipe = None  # type: Any
    PipeSendStream = None  # type: Any
    PipeReceiveStream = None  # type: Any
    PipeSendChannel = None  # type: Any
    PipeReceiveChannel = None  # type: Any


async def make_pipe_stream() -> "Tuple[PipeSendStream, PipeReceiveStream]":
    """Makes a new pair of byte-oriented pipes."""
    (r, w) = pipe()
    assert not (PipeModes.PIPE_READMODE_MESSAGE & get_pipe_state(r))
    return PipeSendStream(w), PipeReceiveStream(r)


async def make_pipe_channel() -> "Tuple[PipeSendChannel, PipeReceiveChannel]":
    """Makes a new pair of message-oriented pipes."""
    (r_channel, w_channel) = Pipe(duplex=False)
    (r, w) = r_channel.fileno(), w_channel.fileno()
    # XXX: Check internal details haven't changed suddenly
    assert (r_channel._handle, w_channel._handle) == (r, w)
    # XXX: Sabotage _ConnectionBase __del__
    (r_channel._handle, w_channel._handle) = (None, None)
    # XXX: Check internal details haven't changed suddenly
    assert r_channel.closed and w_channel.closed
    assert PipeModes.PIPE_READMODE_MESSAGE & get_pipe_state(r)
    return PipeSendChannel(w), PipeReceiveChannel(r)


async def test_pipe_typecheck():
    with pytest.raises(TypeError):
        PipeSendStream(1.0)
    with pytest.raises(TypeError):
        PipeReceiveStream(None)
    with pytest.raises(TypeError):
        PipeSendChannel(1.0)
    with pytest.raises(TypeError):
        PipeReceiveChannel(None)


async def test_pipe_stream_error_on_close():
    # Make sure we correctly handle a failure from kernel32.CloseHandle
    r, w = pipe()

    send_stream = PipeSendStream(w)
    receive_stream = PipeReceiveStream(r)

    assert kernel32.CloseHandle(_handle(r))
    assert kernel32.CloseHandle(_handle(w))

    with pytest.raises(OSError):
        await send_stream.aclose()
    with pytest.raises(OSError):
        await receive_stream.aclose()


async def test_pipe_channel_error_on_close():
    # Make sure we correctly handle a failure from kernel32.CloseHandle
    send_channel, receive_channel = await make_pipe_channel()

    assert kernel32.CloseHandle(_handle(receive_channel._handle_holder.handle))
    assert kernel32.CloseHandle(_handle(send_channel._handle_holder.handle))

    with pytest.raises(OSError):
        await send_channel.aclose()
    with pytest.raises(OSError):
        await receive_channel.aclose()


async def test_closed_resource_error():
    send_stream, receive_stream = await make_pipe_stream()

    await send_stream.aclose()
    with pytest.raises(_core.ClosedResourceError):
        await send_stream.send_all(b"Hello")

    send_channel, receive_channel = await make_pipe_channel()

    with pytest.raises(_core.ClosedResourceError):
        async with _core.open_nursery() as nursery:
            nursery.start_soon(receive_channel.receive)
            await wait_all_tasks_blocked(0.01)
            await receive_channel.aclose()
    await send_channel.aclose()
    with pytest.raises(_core.ClosedResourceError):
        await send_channel.send(b"Hello")


async def test_pipe_streams_combined():
    write, read = await make_pipe_stream()
    count = 2 ** 20
    replicas = 3

    async def sender():
        async with write:
            big = bytearray(count)
            for _ in range(replicas):
                await write.send_all(big)

    async def reader():
        async with read:
            await wait_all_tasks_blocked()
            total_received = 0
            while True:
                # 5000 is chosen because it doesn't evenly divide 2**20
                received = len(await read.receive_some(5000))
                if not received:
                    break
                total_received += received

            assert total_received == count * replicas

    async with _core.open_nursery() as nursery:
        nursery.start_soon(sender)
        nursery.start_soon(reader)


async def test_pipe_channels_combined():
    async def sender():
        async with write:
            b = bytearray(count)
            for _ in range(replicas):
                await write.send(b)

    async def reader():
        async with read:
            await wait_all_tasks_blocked()
            total_received = 0
            async for b in read:
                total_received += len(b)

            assert total_received == count * replicas

    for count in (8, DEFAULT_RECEIVE_SIZE, 2 ** 20):
        for replicas in (1, 2, 3):
            write, read = await make_pipe_channel()
            async with _core.open_nursery() as nursery:
                nursery.start_soon(sender)
                nursery.start_soon(reader)


async def test_async_with_stream():
    w, r = await make_pipe_stream()
    async with w, r:
        pass

    with pytest.raises(_core.ClosedResourceError):
        await w.send_all(b"")
    with pytest.raises(_core.ClosedResourceError):
        await r.receive_some(10)


async def test_async_with_channel():
    w, r = await make_pipe_channel()
    async with w, r:
        pass

    with pytest.raises(_core.ClosedResourceError):
        await w.send(None)
    with pytest.raises(_core.ClosedResourceError):
        await r.receive()


async def test_close_stream_during_write():
    w, r = await make_pipe_stream()
    async with _core.open_nursery() as nursery:

        async def write_forever():
            with pytest.raises(_core.ClosedResourceError) as excinfo:
                while True:
                    await w.send_all(b"x" * 4096)
            assert "another task" in str(excinfo.value)

        nursery.start_soon(write_forever)
        await wait_all_tasks_blocked(0.1)
        await w.aclose()


async def test_close_channel_during_write():
    w, r = await make_pipe_channel()
    async with _core.open_nursery() as nursery:

        async def write_forever():
            with pytest.raises(_core.ClosedResourceError) as excinfo:
                while True:
                    await w.send(b"x" * 4096)
            assert "another task" in str(excinfo.value)

        nursery.start_soon(write_forever)
        await wait_all_tasks_blocked(0.1)
        await w.aclose()


async def test_pipe_fully():
    # passing make_clogged_pipe tests wait_send_all_might_not_block, and we
    # can't implement that on Windows
    await check_one_way_stream(make_pipe_stream, None)
