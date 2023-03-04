import weakref

import trio
from ._core import enable_ki_protection
from ._core._windows_cffi import (
    ffi,
    kernel32,
    ErrorCodes,
    raise_winerror,
    _handle,
    _check,
)


@enable_ki_protection
async def WaitForSingleObject(obj):
    """Async and cancellable variant of WaitForSingleObject. Windows only.

    Args:
      handle: A Win32 handle, as a Python integer.

    Raises:
      OSError: If the handle is invalid, e.g. when it is already closed.

    """
    await trio.lowlevel.checkpoint_if_cancelled()
    # Allow ints or whatever we can convert to a win handle
    handle = _handle(obj)

    # Quick check; we might not even need to spawn a thread. The zero
    # means a zero timeout; this call never blocks. We also exit here
    # if the handle is already closed for some reason.
    retcode = kernel32.WaitForSingleObject(handle, 0)
    if retcode == ErrorCodes.WAIT_FAILED:
        raise_winerror()
    elif retcode != ErrorCodes.WAIT_TIMEOUT:
        await trio.lowlevel.cancel_shielded_checkpoint()
        return

    # Wait for a thread that waits for two handles: the handle plus a handle
    # that we can use to cancel the thread.
    cancel_handle = _check(kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL))

    # Close the handle via weakref because (a) managing within Trio had a tricky
    # race condition (GH-1271) and (b) we don't care precisely when it happens
    cancel_handle_address = int(ffi.cast("intptr_t", cancel_handle))

    def cleanup():
        # regenerate the cancel_handle from an int, so we don't create
        # a reference cycle that keeps cancel_handle alive
        _check(kernel32.CloseHandle(_handle(cancel_handle_address)))

    weakref.finalize(cancel_handle, cleanup)

    try:
        await trio.to_thread.run_sync(
            WaitForMultipleObjects_sync,
            handle,
            cancel_handle,
            cancellable=True,
            limiter=trio.CapacityLimiter(1),
        )
    except trio.Cancelled:
        # Clean up our thread. We get here because this task was cancelled,
        # so we also want to set the cancel handle to stop the thread.
        _check(kernel32.SetEvent(cancel_handle))


def WaitForMultipleObjects_sync(*handles):
    """Wait for any of the given Windows handles to be signaled."""
    n = len(handles)
    handle_arr = ffi.new(f"HANDLE[{n}]")
    for i in range(n):
        handle_arr[i] = handles[i]
    timeout = 0xFFFFFFFF  # INFINITE
    retcode = kernel32.WaitForMultipleObjects(n, handle_arr, False, timeout)  # blocking
    if retcode == ErrorCodes.WAIT_FAILED:
        raise_winerror()
