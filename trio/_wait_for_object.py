import threading
import time
import warnings
from collections import defaultdict

import attr
from sortedcontainers import SortedKeyList

from . import _core
from ._core._windows_cffi import (
    ffi,
    kernel32,
    ErrorCodes,
    raise_winerror,
    _handle,
)

MAXIMUM_WAIT_OBJECTS = 64


def WaitForMultipleObjects_sync(*handles):
    """Wait for any of the given Windows handles to be signaled."""
    n = len(handles)
    assert n <= MAXIMUM_WAIT_OBJECTS
    handle_arr = ffi.new("HANDLE[]", n)
    for i in range(n):
        handle_arr[i] = handles[i]
    timeout = 0xFFFFFFFF  # INFINITE
    retcode = kernel32.WaitForMultipleObjects(n, handle_arr, False, timeout)  # blocking
    if retcode == ErrorCodes.WAIT_FAILED:
        raise_winerror()
    elif retcode >= ErrorCodes.WAIT_ABANDONED:  # pragma: no cover
        # We should never abandon handles but who knows
        retcode -= ErrorCodes.WAIT_ABANDONED
        warnings.warn(RuntimeWarning("Abandoned Mutex: {}".format(handles[retcode])))
    return retcode


@attr.s(slots=True, frozen=True, eq=False)
class WaitJob:
    handle = attr.ib()
    callback = attr.ib()


def _is_signaled(handle):
    # The zero means a zero timeout; this call never blocks.
    retcode = kernel32.WaitForSingleObject(handle, 0)
    if retcode == ErrorCodes.WAIT_FAILED:
        raise_winerror()
    return retcode != ErrorCodes.WAIT_TIMEOUT


class WaitPool:
    def __init__(self):
        self._callbacks_by_handle = defaultdict(list)
        self._wait_group_by_handle = {}
        self._size_sorted_wait_groups = SortedKeyList(key=len)
        self.lock = threading.Lock()

    def add(self, handle, callback):
        # Shortcut if we are already waiting on this handle
        if handle in self._callbacks_by_handle:
            self._callbacks_by_handle[handle].append(callback)
            return

        wait_group_index = (
            self._size_sorted_wait_groups.bisect_key_left(MAXIMUM_WAIT_OBJECTS) - 1
        )
        if wait_group_index == -1:
            # _size_sorted_wait_groups is empty or every group is full
            wait_group = WaitGroup()
        else:
            wait_group = self._size_sorted_wait_groups.pop(wait_group_index)
            wait_group.cancel_soon()

        wait_group.add(handle)
        self._callbacks_by_handle[handle].append(callback)
        self._wait_group_by_handle[handle] = wait_group
        self._size_sorted_wait_groups.add(wait_group)
        wait_group.wait_soon()

    def remove(self, handle, callback):
        if handle not in self._callbacks_by_handle:
            return False

        wait_jobs = self._callbacks_by_handle[handle]

        # discard the data associated with this cancel_token
        # This should never raise IndexError because of how we obtain wait_jobs
        wait_jobs.remove(callback)
        if wait_jobs:
            # no cleanup or thread interaction needed
            return True

        # remove handle from the pool
        del self._callbacks_by_handle[handle]
        wait_group = self._wait_group_by_handle.pop(handle)
        self._size_sorted_wait_groups.remove(wait_group)
        wait_group.remove(handle)

        # free any thread waiting on this group
        wait_group.cancel_soon()

        if len(wait_group) > 1:
            # more waiting needed on other handles
            self._size_sorted_wait_groups.add(wait_group)
            wait_group.wait_soon()
        else:
            # Just the cancel handle left, thread will clean up
            pass

        return True

    def execute_and_remove(self, wait_group, signaled_handle_index):
        self._size_sorted_wait_groups.remove(wait_group)
        signaled_handle = wait_group.pop(signaled_handle_index)
        if len(wait_group) > 1:
            self._size_sorted_wait_groups.add(wait_group)
        for callback in self._callbacks_by_handle[signaled_handle]:
            callback()
        del self._callbacks_by_handle[signaled_handle]


WAIT_POOL = WaitPool()


class WaitGroup:
    def __init__(self):
        self._wait_handles = []
        self._cancel_handle = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)

    def __len__(self):
        return len(self._wait_handles) + 1  # include cancel_handle

    def pop(self, index):
        return self._wait_handles.pop(index)

    def add(self, handle):
        return self._wait_handles.append(handle)

    def remove(self, handle):
        return self._wait_handles.remove(handle)

    def wait_soon(self):
        trio_token = _core.current_trio_token()
        cancel_handle = self._cancel_handle

        def fn():
            try:
                self.drain_as_completed(cancel_handle)
            finally:
                kernel32.CloseHandle(cancel_handle)

        def deliver(outcome):
            # blow up trio if the thread raises so we get a traceback
            trio_token.run_sync_soon(outcome.unwrap)

        _core.start_thread_soon(fn, deliver)

    def cancel_soon(self):
        kernel32.SetEvent(self._cancel_handle)
        self._cancel_handle = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)

    def drain_as_completed(self, cancel_handle):
        while True:
            signaled_handle_index = (
                WaitForMultipleObjects_sync(cancel_handle, *self._wait_handles) - 1
            )
            with WAIT_POOL.lock:
                # Race condition: cancel_handle may have been signalled after a
                # wakeup on another handle. Cancel takes priority.
                if _is_signaled(cancel_handle):
                    return

                # a handle other than the cancel_handle fired
                WAIT_POOL.execute_and_remove(self, signaled_handle_index)
                if not self._wait_handles:
                    return


def UnregisterWait(cancel_token):
    """Trio thread cache variant of UnregisterWait.

    Args:
      cancel_token: Whatever was returned by RegisterWaitForSingleObject.

    """

    handle = cancel_token.handle

    # give up if handle been triggered
    if _is_signaled(handle):
        return ErrorCodes.ERROR_IO_PENDING

    with WAIT_POOL.lock:
        return WAIT_POOL.remove(handle, cancel_token.callback)


def RegisterWaitForSingleObject(handle, callback):
    """Trio thread cache variant of RegisterWaitForSingleObject.

    Args:
      handle: A valid Win32 handle. This should be guaranteed by WaitForSingleObject.

      callback: A Python function.

    Returns:
      cancel_token: An opaque Python object that can be used with UnregisterWait.

    Callbacks run with semantics equivalent to
    WT_EXECUTEINWAITTHREAD | WT_EXECUTEONLYONCE

    Callbacks are run in a trio system thread, so they must not raise errors.

    """
    cancel_token = WaitJob(handle, callback)
    with WAIT_POOL.lock:
        WAIT_POOL.add(handle, callback)

    return cancel_token


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

    # Quick check; we might not even need to spawn a thread.  We also exit here
    # if the handle is already closed for some reason.
    if _is_signaled(handle):
        return

    task = _core.current_task()
    trio_token = _core.current_trio_token()
    # This register transforms the _core.Abort.FAILED case from pulsed (on while
    # the cffi callback is running) to level triggered
    reschedule_in_flight = [False]

    def wakeup():
        reschedule_in_flight[0] = True
        try:
            trio_token.run_sync_soon(_core.reschedule, task, idempotent=True)
        except _core.RunFinishedError:  # pragma: no cover
            # No need to throw a fit here, the task can't be rescheduled anyway
            pass

    cancel_token = RegisterWaitForSingleObject(handle, wakeup)

    def abort(raise_cancel):
        retcode = UnregisterWait(cancel_token)
        if retcode == ErrorCodes.ERROR_IO_PENDING or reschedule_in_flight[0]:
            # The callback is about to wake up our task
            return _core.Abort.FAILED
        elif retcode:
            return _core.Abort.SUCCEEDED
        else:  # pragma: no cover
            raise RuntimeError(f"Unexpected retcode: {retcode}")

    await _core.wait_task_rescheduled(abort)
    # Unconditional unregister if not cancelled. Resource cleanup? MSDN says,
    # "Even wait operations that use WT_EXECUTEONLYONCE must be canceled."
    UnregisterWait(cancel_token)
