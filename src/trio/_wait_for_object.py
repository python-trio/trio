from __future__ import annotations

import math
import threading

import trio

from ._core._windows_cffi import (
    CData,
    ErrorCodes,
    _handle,
    ffi,
    handle_array,
    kernel32,
    raise_winerror,
)


async def WaitForSingleObject(obj: int | CData) -> None:
    """Async and cancellable variant of WaitForSingleObject. Windows only.

    Args:
      handle: A Win32 handle, as a Python integer.

    Raises:
      OSError: If the handle is invalid, e.g. when it is already closed.

    """
    # Allow ints or whatever we can convert to a win handle
    handle = _handle(obj)

    # Quick check; we might not even need to spawn a thread. The zero
    # means a zero timeout; this call never blocks. We also exit here
    # if the handle is already closed for some reason.
    retcode = kernel32.WaitForSingleObject(handle, 0)
    if retcode == ErrorCodes.WAIT_FAILED:
        raise_winerror()
    elif retcode != ErrorCodes.WAIT_TIMEOUT:
        return

    # Wait for a thread that waits for two handles: the handle plus a handle
    # that we can use to cancel the thread.
    cancel_handle = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    limiter = trio.CapacityLimiter(math.inf)
    lock = threading.Lock()
    task_finished = False
    worker_finished = False

    def wait_in_thread() -> None:
        nonlocal worker_finished
        try:
            WaitForMultipleObjects_sync(handle, cancel_handle)
        finally:
            with lock:
                worker_finished = True
                if task_finished:
                    kernel32.CloseHandle(cancel_handle)

    try:
        await trio.to_thread.run_sync(
            wait_in_thread,
            abandon_on_cancel=True,
            limiter=limiter,
        )
    finally:
        with lock:
            # The worker may not have started waiting yet. Whichever side
            # finishes last closes the handle, after it can no longer be used
            # by either WaitForMultipleObjects or SetEvent.
            kernel32.SetEvent(cancel_handle)
            task_finished = True
            # run_sync retains its limiter token until the worker finishes.
            # No token means cancellation or startup failure prevented a
            # worker from starting, or its result has already been delivered.
            if worker_finished or not limiter.borrowed_tokens:
                kernel32.CloseHandle(cancel_handle)


def WaitForMultipleObjects_sync(*handles: int | CData) -> None:
    """Wait for any of the given Windows handles to be signaled."""
    n = len(handles)
    handle_arr = handle_array(n)
    for i in range(n):
        handle_arr[i] = handles[i]
    timeout = 0xFFFFFFFF  # INFINITE
    retcode = kernel32.WaitForMultipleObjects(n, handle_arr, False, timeout)  # blocking
    if retcode == ErrorCodes.WAIT_FAILED:
        raise_winerror()
