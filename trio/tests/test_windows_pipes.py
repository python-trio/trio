import errno
import select

import os
import pytest

from .._core.tests.tutil import gc_collect_harder
from .. import _core, move_on_after
from ..testing import wait_all_tasks_blocked, check_one_way_stream

windows = os.name == "nt"
pytestmark = pytest.mark.skipif(not windows, reason="windows only")
if windows:
    from .._windows_pipes import PipeSendStream, PipeReceiveStream, make_pipe


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


async def test_pipe_errors():
    with pytest.raises(TypeError):
        PipeReceiveStream(None)


async def test_async_with():
    w, r = await make_pipe()
    async with w, r:
        pass

    assert w._closed
    assert r._closed

    # test failue-to-close
    w._closed = False
    with pytest.raises(OSError):
        await w.aclose()


async def test_close_during_write():
    w, r = await make_pipe()
    async with _core.open_nursery() as nursery:

        async def write_forever():
            with pytest.raises(_core.ClosedResourceError) as excinfo:
                while True:
                    await w.send_all(b"x" * 4096)
            assert "another task" in str(excinfo)

        nursery.start_soon(write_forever)
        await wait_all_tasks_blocked(0.1)
        await w.aclose()


async def test_pipe_fully():
    # passing make_clogged_pipe tests wait_send_all_might_not_block, and we
    # can't implement that on Windows
    await check_one_way_stream(make_pipe, None)
