import math
import warnings
from collections import defaultdict

import outcome
import attr
from sortedcontainers import SortedKeyList

import trio
from ._core import RunVar
from ._core._windows_cffi import (
    ffi,
    kernel32,
    ErrorCodes,
    raise_winerror,
    _handle,
)


def WaitForMultipleObjects_sync(*handles):
    """Wait for any of the given Windows handles to be signaled."""
    n = len(handles)
    handle_arr = ffi.new("HANDLE[{}]".format(n))
    for i in range(n):
        handle_arr[i] = handles[i]
    timeout = 0xFFFFFFFF  # INFINITE
    retcode = kernel32.WaitForMultipleObjects(n, handle_arr, False, timeout)  # blocking
    if retcode == ErrorCodes.WAIT_FAILED:
        raise_winerror()
    elif retcode >= 0x80:  # We should never abandon handles but who knows
        retcode -= 0x80
        warnings.warn(RuntimeWarning("Abandoned Mutex: {}".format(handles[retcode])))
    return retcode


_wait_local = RunVar("waiters")


@attr.s(slots=True)
class HandleWaiter:
    callback = attr.ib()
    context = attr.ib()
    cancel_token = attr.ib()
    cancel_handle = attr.ib()


@attr.s(slots=True, frozen=True)
class WaitJob:
    handle = attr.ib()
    callback = attr.ib()
    context = attr.ib()


def _make_cancel_token(job):
    """Does any work necessary to transform a job into a cancel_token"""
    # Use id to ensure uniqueness of the token, but uniqueness is only
    # guaranteed as long as the job tuple lives, so pack it along too
    return id(job), job


def _is_signaled(handle):
    # The zero means a zero timeout; this call never blocks.
    retcode = kernel32.WaitForSingleObject(handle, 0)
    if retcode == ErrorCodes.WAIT_FAILED:
        raise_winerror()
    return retcode != ErrorCodes.WAIT_TIMEOUT


def _get_wait_structures():
    try:
        wait_groups, handle_waiter_map, token_handle_map = _wait_local.get()
    except LookupError:
        handle_waiter_map = defaultdict(list)
        token_handle_map = {}
        wait_groups = SortedKeyList(key=len)
        _wait_local.set((wait_groups, handle_waiter_map, token_handle_map))
    return wait_groups, handle_waiter_map, token_handle_map


def _pop_wait_group_by_cancel_handle(wait_groups, cancel_handle):
    for i, wait_group in enumerate(wait_groups):
        if wait_group[0] == cancel_handle:
            del wait_groups[i]
            return wait_group


async def _drain_as_completed(wait_group):
    wait_groups, handle_waiter_map, token_handle_map = _get_wait_structures()
    while len(wait_group) > 1:
        # need a local name in case someone changes it while in thread
        cancel_handle = wait_group[0]
        try:
            retcode = await trio.to_thread.run_sync(
                WaitForMultipleObjects_sync,
                *wait_group,
                cancellable=True,  # should only happen on trio exit
                limiter=trio.CapacityLimiter(math.inf),
            )
        except trio.Cancelled:
            # free thread and our event for trio exit
            kernel32.SetEvent(cancel_handle)
            kernel32.CloseHandle(cancel_handle)
            raise

        if retcode == 0:
            # cancel_handle activated by another task that will handle things
            assert _is_signaled(cancel_handle)
            kernel32.CloseHandle(cancel_handle)
            return
        # Race condition: cancel_handle may have been signalled after a wakeup
        # on another handle. Treat it as a legitimate cancel.
        if _is_signaled(cancel_handle):
            kernel32.CloseHandle(cancel_handle)
            return

        assert cancel_handle == wait_group[0], "cancel_handle unexpectedly changed"
        # a handle other than the cancel_handle fired
        _pop_wait_group_by_cancel_handle(wait_groups, cancel_handle)
        handle = wait_group.pop(retcode)
        wait_groups.add(wait_group)
        for waiter in handle_waiter_map.pop(handle):
            token_handle_map.pop(waiter.cancel_token)
            outcome.capture(waiter.callback, waiter.context)
        del waiter, handle
    # only the cancel handle remains, clean up and return
    _pop_wait_group_by_cancel_handle(wait_groups, cancel_handle)
    kernel32.CloseHandle(cancel_handle)


def UnregisterWait(cancel_token):
    """Trio native variant of UnregisterWait.

    Args:
      cancel_token: Whatever was returned by RegisterWaitForSingleObject.

    """
    wait_groups, handle_waiter_map, token_handle_map = _get_wait_structures()

    if cancel_token not in token_handle_map:
        return True

    handle = token_handle_map.pop(cancel_token)
    # give up if handle been triggered
    if _is_signaled(handle):
        return False
    waiters = handle_waiter_map[handle]

    if len(waiters) > 1:
        # simply discard the data associated with this cancel_token
        for i, waiter in enumerate(waiters):
            if cancel_token == waiter[2]:
                del waiters[i]
                return True
        else:
            raise RuntimeError(
                "Nothing found to cancel with cancel_token {}".format(cancel_token)
            )

    assert waiters
    # This cancel_token points to a handle that only has one waiter
    cancel_handle = waiters[0].cancel_handle
    # free any thread waiting on this group
    kernel32.SetEvent(cancel_handle)
    del handle_waiter_map[handle]

    # extract it from its wait_group
    # remove it from wait_groups as well as we will change its size
    wait_group = _pop_wait_group_by_cancel_handle(wait_groups, cancel_handle)
    assert wait_group is not None
    wait_group.remove(handle)
    del handle

    if len(wait_group) == 1:
        # Just the cancel handle left, we're done
        return True

    # make a new cancel_handle and assign it to all waiters of all other handles
    cancel_handle = wait_group[0] = kernel32.CreateEventA(
        ffi.NULL, True, False, ffi.NULL
    )
    for handle in wait_group[1:]:
        for waiter in handle_waiter_map[handle]:
            waiter.cancel_handle = cancel_handle

    trio.lowlevel.spawn_system_task(_drain_as_completed, wait_group)
    wait_groups.add(wait_group)
    return True


def RegisterWaitForSingleObject(handle, callback, context):
    """Trio native variant of RegisterWaitForSingleObject.

    Args:
      handle: A valid Win32 handle. This should be guaranteed by WaitForSingleObject.

      callback: A Python function, called with context as an argument

      context: A Python object, used as an argument to callback

    Returns:
      cancel_token: An opaque Python object that can be used with UnregisterWait

    Callbacks run with semantics equivalent to
    WT_EXECUTEINWAITTHREAD | WT_EXECUTEONLYONCE

    Callbacks are run in a trio system task, so they must not raise errors

    """
    job = WaitJob(handle, callback, context)
    cancel_token = _make_cancel_token(job)
    wait_groups, handle_waiter_map, token_handle_map = _get_wait_structures()
    # Shortcut if we are already waiting on this handle
    if handle in handle_waiter_map:
        waiters = handle_waiter_map[handle]
        # assumes no empty waiters lists in handle_waiter_map
        cancel_handle = waiters[0].cancel_handle
        waiters.append(HandleWaiter(callback, context, cancel_token, cancel_handle,))
        return cancel_token

    cancel_handle = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    wait_group_index = wait_groups.bisect_key_left(64) - 1
    if wait_group_index == -1:
        # wait_groups is empty or every group is full with 64
        wait_group = [cancel_handle]
    else:
        wait_group = wait_groups.pop(wait_group_index)
        # wake this particular group
        # cancel handle is on the left by construction
        kernel32.SetEvent(wait_group[0])
        # overwrite with fresh cancel_handle since PulseEvent/ResetEvent could be flaky
        wait_group[0] = cancel_handle
        # update each waiter with the new cancel_handle
        for waiter in handle_waiter_map[handle]:
            waiter.cancel_handle = cancel_handle
    handle_waiter_map[handle].append(
        HandleWaiter(callback, context, cancel_token, cancel_handle)
    )
    token_handle_map[cancel_token] = handle
    wait_group.append(handle)

    trio.lowlevel.spawn_system_task(_drain_as_completed, wait_group)
    wait_groups.add(wait_group)

    return cancel_token


async def WaitForSingleObject(obj):
    """Async and cancellable variant of WaitForSingleObject. Windows only.

    Args:
      obj: A Win32 handle, as a Python integer.

    Raises:
      OSError: If the handle is invalid, e.g. when it is already closed.

    """
    # Allow ints or whatever we can convert to a win handle
    handle = _handle(obj)

    # Quick check; we might not even need to spawn a thread.  We also exit here
    # if the handle is already closed for some reason.
    if _is_signaled(handle):
        return

    cancel_token = RegisterWaitForSingleObject(
        handle, trio.lowlevel.reschedule, trio.lowlevel.current_task()
    )

    def abort(raise_cancel):
        if UnregisterWait(cancel_token):
            return trio.lowlevel.Abort.SUCCEEDED
        else:
            return trio.lowlevel.Abort.FAILED

    await trio.lowlevel.wait_task_rescheduled(abort)
    # TODO: handle failure of UnregisterWait
