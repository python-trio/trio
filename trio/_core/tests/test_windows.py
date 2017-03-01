import os
import pytest

on_windows = (os.name == "nt")
# Mark all the tests in this file as being windows-only
pytestmark = pytest.mark.skipif(not on_windows, reason="windows only")

from ... import _core
if on_windows:
    from .._windows_cffi import ffi, kernel32

async def test_completion_key_listen():
    async def post(key):
        iocp = ffi.cast("HANDLE", _core.current_iocp())
        for i in range(10):
            print("post", i)
            if i % 3 == 0:
                await _core.yield_briefly()
            success = kernel32.PostQueuedCompletionStatus(
                iocp, i, key, ffi.NULL)
            assert success

    with _core.monitor_completion_key() as (key, queue):
        async with _core.open_nursery() as nursery:
            task = nursery.spawn(post, key)
            i = 0
            print("loop")
            async for batch in queue:  # pragma: no branch
                print("got some", batch)
                for info in batch:
                    assert info.lpOverlapped == 0
                    assert info.dwNumberOfBytesTransferred == i
                    i += 1
                if i == 10:
                    break
            print("end loop")


# XX test setting the iomanager._iocp to something weird to make sure that the
# IOCP thread can send exceptions back to the main thread
