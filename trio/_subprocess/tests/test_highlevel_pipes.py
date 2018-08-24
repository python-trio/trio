import os
import pytest

from ... import _core
from ..unix_pipes import PipeSendStream, PipeReceiveStream, make_pipe
from ...testing import (
    wait_all_tasks_blocked, check_one_way_stream
)

pytestmark = pytest.mark.skipif(
    not hasattr(os, "pipe2"), reason="pipes require os.pipe2()"
)


async def test_send_pipe():
    r, w = os.pipe2(os.O_NONBLOCK)
    send = PipeSendStream(w)
    assert send.fileno() == w
    await send.send_all(b"123")
    assert (os.read(r, 8)) == b"123"

    os.close(r)
    os.close(w)


async def test_receive_pipe():
    r, w = os.pipe2(os.O_NONBLOCK)
    recv = PipeReceiveStream(r)
    assert (recv.fileno()) == r
    os.write(w, b"123")
    assert (await recv.receive_some(8)) == b"123"

    os.close(r)
    os.close(w)


async def test_pipes_combined():
    write, read = await make_pipe()
    count = 2**20

    async def sender():
        big = bytearray(count)
        await write.send_all(big)

    async def reader():
        await wait_all_tasks_blocked()
        received = 0
        while received < count:
            received += len(await read.receive_some(4096))

        assert received == count

    async with _core.open_nursery() as n:
        n.start_soon(sender)
        n.start_soon(reader)

    await read.aclose()
    await write.aclose()


async def test_send_on_closed_pipe():
    write, read = await make_pipe()
    await write.aclose()

    with pytest.raises(_core.ClosedResourceError):
        await write.send_all(b"123")

    await read.aclose()


async def test_pipe_errors():
    with pytest.raises(TypeError):
        PipeReceiveStream(None)

    with pytest.raises(ValueError):
        await PipeReceiveStream(0).receive_some(0)


#async def test_pipe_fully():
#    await check_one_way_stream(make_pipe, None)
