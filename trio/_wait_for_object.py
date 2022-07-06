import contextlib
import threading
import warnings

from sortedcontainers import SortedKeyList

from . import _core
from ._core._windows_cffi import (
    ffi,
    kernel32,
    ErrorCodes,
    raise_winerror,
    _handle,
    _is_signaled,
)


MAXIMUM_WAIT_OBJECTS = 64


def WaitForMultipleObjects_sync(handles):
    """Wait for any of the given Windows handles to be signaled.

    It's very important that `handles` length not change, so prefer using a tuple"""
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
    return handles[retcode]


class WaitPool:
    """A pool of threads and handles that need waiting.

    Only call methods after acquiring the lock!
    """

    def __init__(self):
        self._handle_map = {}
        self._size_sorted_wait_groups = SortedKeyList(key=len)
        self.lock = threading.Lock()

    def __contains__(self, item):
        return item in self._handle_map

    def add(self, handle, callback):
        # Shortcut if we are already waiting on this handle
        if handle in self._handle_map:
            self._handle_map[handle][0].add(callback)
            return

        try:
            wait_group = self._size_sorted_wait_groups.pop()
        except IndexError:
            # pool is empty or every group is full
            wait_group = spawn_wait_group()
        else:
            # need a wake to make sure the group waits on the handle ASAP
            kernel32.SetEvent(wait_group[0])

        self._handle_map[handle] = ({callback}, wait_group)
        with self.mutating(wait_group):
            wait_group.append(handle)

    def remove(self, handle, callback):
        callbacks, wait_group = self._handle_map[handle]
        callbacks.remove(callback)
        if callbacks:
            # no cleanup or thread interaction needed
            return

        del self._handle_map[handle]
        with self.mutating(wait_group):
            wait_group.remove(handle)

        if len(wait_group) == 1:
            # need a wake to make sure this thread exits promptly
            kernel32.SetEvent(wait_group[0])

    def execute_callbacks(self, handle):
        # also discards our internal reference to the handle
        for callback in self._handle_map.pop(handle)[0]:
            callback()

    @contextlib.contextmanager
    def mutating(self, wait_group):
        # SortedKeyList can't cope with mutating keys, so
        # remove and re-add to maintain sort order
        self._size_sorted_wait_groups.discard(wait_group)
        try:
            yield
        finally:
            # if SortedKeyList has many equal values, remove() performance degrades
            # from O(log(n)) to O(n), so we don't keep full or empty groups inside
            if 1 < len(wait_group) < MAXIMUM_WAIT_OBJECTS:
                self._size_sorted_wait_groups.add(wait_group)


WAIT_POOL = WaitPool()


def spawn_wait_group():
    """Only to be used within WaitPool"""
    trio_token = _core.current_trio_token()
    # maintain a wake handle at index 0, initially the event is SET
    wait_group = [kernel32.CreateEventA(ffi.NULL, True, True, ffi.NULL)]

    def remove_as_signaled():
        n_handles = 2
        wait_group_tuple = tuple(wait_group)
        while n_handles > 1:  # quit thread when only wake handle remains
            signaled_handle = WaitForMultipleObjects_sync(wait_group_tuple)
            with WAIT_POOL.lock:
                if signaled_handle is wait_group[0]:
                    # A handle has been added or removed from this group
                    # Reset is OK here because only this thread waits on the event
                    kernel32.ResetEvent(wait_group[0])
                elif signaled_handle in WAIT_POOL:  # pragma: no branch
                    # This check is almost always true, but guards against an
                    # Extremely rare race condition where a handle is signaled
                    # just before it is removed from the pool
                    with WAIT_POOL.mutating(wait_group):
                        wait_group.remove(signaled_handle)
                    WAIT_POOL.execute_callbacks(signaled_handle)
                # calculate these while holding the lock
                n_handles = len(wait_group)
                wait_group_tuple = tuple(wait_group)

    def deliver(outcome):
        # if the process exits before this group's daemon thread, this won't be
        # called, but in that case the OS will clean up our handle for us
        kernel32.CloseHandle(wait_group[0])
        # blow up trio if the thread raises so that we get a traceback
        try:
            trio_token.run_sync_soon(outcome.unwrap)
        except _core.RunFinishedError:  # pragma: no cover
            # if trio is already gone, here is better than nowhere
            outcome.unwrap()

    _core.start_thread_soon(remove_as_signaled, deliver)
    return wait_group


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
    reschedule_in_flight = [False]

    def wakeup():
        if reschedule_in_flight[0]:  # pragma: no cover
            raise RuntimeError("Extra wakeup occurred on this task")
        reschedule_in_flight[0] = True
        try:
            trio_token.run_sync_soon(_core.reschedule, task)
        except _core.RunFinishedError:  # pragma: no cover
            # No need to throw a fit here, the task can't be rescheduled anyway
            pass

    with WAIT_POOL.lock:
        WAIT_POOL.add(handle, wakeup)

    def abort(raise_cancel):
        with WAIT_POOL.lock:
            if reschedule_in_flight[0]:  # pragma: no cover
                # The callback is about to wake up our task
                return _core.Abort.FAILED
            try:
                WAIT_POOL.remove(handle, wakeup)
            except KeyError:  # pragma: no cover
                raise RuntimeError("Extra cancel occurred on this task or handle")
            else:
                return _core.Abort.SUCCEEDED

    await _core.wait_task_rescheduled(abort)
