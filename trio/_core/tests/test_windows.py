import os
import pytest

on_windows = (os.name == "nt")
# Mark all the tests in this file as being windows-only
pytestmark = pytest.mark.skipif(not on_windows, reason="windows only")

from ... import _core
from ... import _timeouts
if on_windows:
    from .._windows_cffi import ffi, kernel32
    from .._io_windows import WaitForSingleObject


async def test_completion_key_listen():
    async def post(key):
        iocp = ffi.cast("HANDLE", _core.current_iocp())
        for i in range(10):
            print("post", i)
            if i % 3 == 0:
                await _core.checkpoint()
            success = kernel32.PostQueuedCompletionStatus(
                iocp, i, key, ffi.NULL
            )
            assert success

    with _core.monitor_completion_key() as (key, queue):
        async with _core.open_nursery() as nursery:
            nursery.start_soon(post, key)
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


async def test_WaitForSingleObject():

    # Set the timeout used in the tests. The resolution of WaitForSingleObject
    # is 0.01 so anything more than a magnitude larger should probably do.
    # If too large, the test become slow and we might need to mark it as @slow.
    TIMEOUT = 0.1

    # Test 1, handle is SET after 1 sec in separate coroutine
    async def handle_setter(handle):
        await _timeouts.sleep(TIMEOUT)
        kernel32.SetEvent(handle)

    handle = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    t0 = _core.current_time()

    async with _core.open_nursery() as nursery:
        nursery.start_soon(WaitForSingleObject, handle)
        nursery.start_soon(handle_setter, handle)

    kernel32.CloseHandle(handle)
    t1 = _core.current_time()
    assert TIMEOUT <= (t1 - t0) < 1.1 * TIMEOUT

    # Test 2, handle is CLOSED after 1 sec
    async def handle_closer(handle):
        await _timeouts.sleep(TIMEOUT)
        kernel32.CloseHandle(handle)

    handle = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    t0 = _core.current_time()

    async with _core.open_nursery() as nursery:
        nursery.start_soon(WaitForSingleObject, handle)
        nursery.start_soon(handle_closer, handle)

    t1 = _core.current_time()
    assert TIMEOUT <= (t1 - t0) < 1.1 * TIMEOUT

    # Test 3, cancelation

    handle = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    t0 = _core.current_time()

    with _timeouts.move_on_after(TIMEOUT):
        await WaitForSingleObject(handle)

    kernel32.CloseHandle(handle)
    t1 = _core.current_time()
    assert TIMEOUT <= (t1 - t0) < 1.1 * TIMEOUT

    # Test 4, already canceled

    handle = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    kernel32.SetEvent(handle)
    t0 = _core.current_time()

    with _timeouts.move_on_after(TIMEOUT):
        await WaitForSingleObject(handle)

    kernel32.CloseHandle(handle)
    t1 = _core.current_time()
    assert (t1 - t0) < 0.5 * TIMEOUT

    # Test 5, already closed

    handle = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    kernel32.CloseHandle(handle)
    t0 = _core.current_time()

    with _timeouts.move_on_after(TIMEOUT):
        await WaitForSingleObject(handle)

    t1 = _core.current_time()
    assert (t1 - t0) < 0.5 * TIMEOUT


# XX test setting the iomanager._iocp to something weird to make sure that the
# IOCP thread can send exceptions back to the main thread
