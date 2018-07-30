from . import _timeouts
from . import _core
from ._threads import run_sync_in_worker_thread
from ._core._windows_cffi import ffi, kernel32, ErrorCodes


async def WaitForSingleObject(handle):
    """Async and cancellable variant of kernel32.WaitForSingleObject().

    Args:
      handle: A win32 handle.

    """
    # Quick check; we might not even need to spawn a thread. The zero
    # means a zero timeout; this call never blocks. We also exit here
    # if the handle is already closed for some reason.
    retcode = kernel32.WaitForSingleObject(handle, 0)
    if retcode != ErrorCodes.WAIT_TIMEOUT:
        return

    class StubLimiter:
        def release_on_behalf_of(self, x):
            pass

        async def acquire_on_behalf_of(self, x):
            pass

    # Wait for a thread that waits for two handles: the handle plus a handle
    # that we can use to cancel the thread.
    cancel_handle = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    try:
        await run_sync_in_worker_thread(
            WaitForMultipleObjects_sync,
            handle,
            cancel_handle,
            cancellable=True,
            limiter=StubLimiter(),
        )
    finally:
        # Clean up our cancel handle. In case we get here because this task was
        # cancelled, we also want to set the cancel_handle to stop the thread.
        kernel32.SetEvent(cancel_handle)
        kernel32.CloseHandle(cancel_handle)


def WaitForMultipleObjects_sync(*handles):
    """Wait for any of the given Windows handles to be signaled.
    
    """
    n = len(handles)
    handle_arr = ffi.new("HANDLE[{}]".format(n))
    for i in range(n):
        handle_arr[i] = handles[i]
    timeout = 0xffffffff  # INFINITE
    kernel32.WaitForMultipleObjects(n, handle_arr, False, timeout)  # blocking
