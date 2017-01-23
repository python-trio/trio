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
            success = kernel32.PostQueuedCompletionStatus(
                iocp, i, key, ffi.NULL)
            assert success

    with _core.completion_key_monitor() as (key, queue):
        try:
            task = await _core.spawn(post, key)
            i = 0
            print("loop")
            async for batch in queue:
                print("got some", batch)
                for info in batch:
                    assert info.lpOverlapped == 0
                    assert info.dwNumberOfBytesTransferred == i
                    i += 1
                if i == 10:
                    break
            print("end loop")
        finally:
            print("joining")
            # have to make sure that post() is finished before exiting this
            # block and relinquishing the completion key
            (await task.join()).unwrap()
