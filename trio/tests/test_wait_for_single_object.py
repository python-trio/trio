import os
from threading import Thread

import pytest

on_windows = (os.name == "nt")
# Mark all the tests in this file as being windows-only
pytestmark = pytest.mark.skipif(not on_windows, reason="windows only")

from .. import _core
from .. import _timeouts
if on_windows:
    from .._core._windows_cffi import ffi, kernel32
    from .._wait_for_single_object import WaitForSingleObject, WaitForMultipleObjects_sync


async def test_WaitForMultipleObjects_sync():
    # One handle
    handle1 = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    t = Thread(target=WaitForMultipleObjects_sync, args=(handle1,))
    t.start()
    kernel32.SetEvent(handle1)
    t.join()  # the test succeeds if we do not block here :)
    kernel32.CloseHandle(handle1)

    # Two handles, signal first
    handle1 = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    handle2 = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    t = Thread(target=WaitForMultipleObjects_sync, args=(handle1, handle2))
    t.start()
    kernel32.SetEvent(handle1)
    t.join()  # the test succeeds if we do not block here :)
    kernel32.CloseHandle(handle1)
    kernel32.CloseHandle(handle2)

    # Two handles, signal seconds
    handle1 = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    handle2 = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    t = Thread(target=WaitForMultipleObjects_sync, args=(handle1, handle2))
    t.start()
    kernel32.SetEvent(handle2)
    t.join()  # the test succeeds if we do not block here :)
    kernel32.CloseHandle(handle1)
    kernel32.CloseHandle(handle2)

    # Closing the handle will not stop the thread. Initiating a wait on a
    # closed handle will fail/return, but closing a handle that is already
    # being waited on will not stop whatever is waiting for it.


async def test_WaitForSingleObject():

    # Set the timeout used in the tests. The resolution of WaitForSingleObject
    # is 0.01 so anything more than a magnitude larger should probably do.
    # If too large, the test become slow and we might need to mark it as @slow.
    TIMEOUT = 0.5

    async def handle_setter(handle):
        await _timeouts.sleep(TIMEOUT)
        kernel32.SetEvent(handle)

    # Test 1, handle is SET after 1 sec in separate coroutine

    handle = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    t0 = _core.current_time()

    async with _core.open_nursery() as nursery:
        nursery.start_soon(WaitForSingleObject, handle)
        nursery.start_soon(handle_setter, handle)

    kernel32.CloseHandle(handle)
    t1 = _core.current_time()
    assert TIMEOUT <= (t1 - t0) < 1.1 * TIMEOUT
    print('test_WaitForSingleObject test 1 OK')

    # Test 2, handle is CLOSED after 1 sec - NOPE, wont work unless we use zero timeout

    pass

    # Test 3, cancellation

    handle = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    t0 = _core.current_time()

    with _timeouts.move_on_after(TIMEOUT):
        await WaitForSingleObject(handle)

    kernel32.CloseHandle(handle)
    t1 = _core.current_time()
    assert TIMEOUT <= (t1 - t0) < 1.1 * TIMEOUT
    print('test_WaitForSingleObject test 3 OK')

    # Test 4, already cancelled

    handle = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    kernel32.SetEvent(handle)
    t0 = _core.current_time()

    with _timeouts.move_on_after(TIMEOUT):
        await WaitForSingleObject(handle)

    kernel32.CloseHandle(handle)
    t1 = _core.current_time()
    assert (t1 - t0) < 0.5 * TIMEOUT
    print('test_WaitForSingleObject test 4 OK')

    # Test 5, already closed

    handle = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    kernel32.CloseHandle(handle)
    t0 = _core.current_time()

    with _timeouts.move_on_after(TIMEOUT):
        await WaitForSingleObject(handle)

    t1 = _core.current_time()
    assert (t1 - t0) < 0.5 * TIMEOUT
    print('test_WaitForSingleObject test 5 OK')
