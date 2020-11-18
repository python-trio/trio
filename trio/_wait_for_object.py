from . import _core
from ._core._windows_cffi import (
    ffi,
    kernel32,
    WaitFlags,
    raise_winerror,
    _handle,
    _is_signaled,
)


@ffi.callback("WAITORTIMERCALLBACK")
def wait_callback(context, timer_or_wait_fired):
    ffi.from_handle(context)()


def UnregisterWait(cancel_token):
    """Python wrapper for kernel32.UnregisterWait.

    Args:
      cancel_token: Whatever was returned by RegisterWaitForSingleObject.

    """
    cancel_token, context_handle = cancel_token
    # have to dereference cancel token i.e. PHANDLE -> HANDLE
    return kernel32.UnregisterWait(cancel_token[0])


def RegisterWaitForSingleObject(handle, callback):
    """Python wrapper for kernel32.RegisterWaitForSingleObject.

    Args:
      handle: A valid Win32 handle. This should be guaranteed by WaitForSingleObject.

      callback: A Python function taking no arguments and definitely not raising
        any errors.

    Returns:
      cancel_token: An opaque object that can be used with UnregisterWait.
        This object must be kept alive until the callback is called or cancelled!

    Callbacks are run with WT_EXECUTEINWAITTHREAD | WT_EXECUTEONLYONCE.

    Callbacks are run in a windows system thread, so they must not raise errors.

    """
    cancel_token = ffi.new("PHANDLE")
    context_handle = ffi.new_handle(callback)
    timeout = 0xFFFFFFFF  # INFINITE
    if not kernel32.RegisterWaitForSingleObject(
        cancel_token,
        handle,
        wait_callback,
        context_handle,
        timeout,
        WaitFlags.WT_EXECUTEINWAITTHREAD | WaitFlags.WT_EXECUTEONLYONCE,
    ):
        raise_winerror()
    # keep context alive by passing it around with cancel_token
    return cancel_token, context_handle


async def WaitForSingleObject(obj):
    """Async and cancellable variant of WaitForSingleObject. Windows only.

    Args:
      obj: A Win32 handle, as a Python integer.

    Raises:
      OSError: If the handle is invalid, e.g. when it is already closed.

    """
    await _core.checkpoint_if_cancelled()
    # Allow ints or whatever we can convert to a win handle
    handle = _handle(obj)

    # Quick check; we might not even need to register the handle.  We also exit here
    # if the handle is already closed for some reason.
    if _is_signaled(handle):
        await _core.cancel_shielded_checkpoint()
        return

    task = _core.current_task()
    trio_token = _core.current_trio_token()

    def wakeup():
        trio_token.run_sync_soon(_core.reschedule, task, idempotent=True)

    cancel_token = RegisterWaitForSingleObject(handle, wakeup)

    def abort(raise_cancel):
        if UnregisterWait(cancel_token):
            return _core.Abort.SUCCEEDED
        else:
            return _core.Abort.FAILED

    await _core.wait_task_rescheduled(abort)
