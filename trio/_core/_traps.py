# These are the only 2 functions that ever yield back to the task runner.

import types
import enum
from functools import wraps

from . import _hazmat

__all__ = ["yield_briefly_no_cancel", "Abort", "yield_indefinitely"]

# Decorator to turn a generator into a well-behaved async function:
def asyncfunction(fn):
    # Set the coroutine flag
    fn = types.coroutine(fn)
    # Then wrap it in an 'async def', to enable the "coroutine was not
    # awaited" warning
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        return await fn(*args, **kwargs)
    return wrapper

@_hazmat
@asyncfunction
def yield_briefly_no_cancel():
    """Introduce a schedule point, but not a cancel point.

    """
    return (yield (yield_briefly_no_cancel,)).unwrap()

# Return values for abort functions
@_hazmat
class Abort(enum.Enum):
    """:class:`enum.Enum` used as the return value from abort functions.

    See :func:`yield_indefinitely` for details.

    .. data:: SUCCEEDED
              FAILED

    """
    SUCCEEDED = 1
    FAILED = 2

@_hazmat
@asyncfunction
def yield_indefinitely(abort_fn):
    """Put the current task to sleep, with cancellation support.

    This is the lowest-level API for blocking in trio. Every time a
    :class:`~trio.Task` blocks, it does so by calling this function.

    This is a tricky interface with no guard rails. If you can use
    :class:`ParkingLot` or the built-in I/O wait functions instead, then you
    should.

    Generally the way it works is that before calling this function, you make
    arrangements for "someone" to call :func:`reschedule` on the current task
    at some later point.

    Then you call :func:`yield_indefinitely`, passing in ``abort_fn``, an
    "abort callback".

    (Terminology: in trio, "aborting" is the process of attempting to
    interrupt a blocked task to deliver a cancellation.)

    There are two possibilities for what happens next:

    1. "Someone" calls :func:`reschedule` on the current task, and
       :func:`yield_indefinitely` returns or raises whatever value or error
       was passed to :func:`reschedule`.

    2. The call's context transitions to a cancelled state (e.g. due to a
       timeout expiring). When this happens, the ``abort_fn`` is called. It's
       interface looks like::

           def abort_fn(raise_cancel):
               ...
               return trio.hazmat.Abort.SUCCEEDED  # or FAILED

       It should attempt to clean up any state associated with this call, and
       in particular, arrange that :func:`reschedule` will *not* be called
       later. If (and only if!) it is successful, then it should return
       :data:`Abort.SUCCEEDED`, in which case the task will automatically be
       rescheduled with an appropriate :exc:`~trio.Cancelled` error.

       Otherwise, it should return :data:`Abort.FAILED`. This means that the
       task can't be cancelled at this time, and still has to make sure that
       "someone" eventually calls :func:`reschedule`.

       At that point there are again two possibilities. You can simply ignore
       the cancellation altogether: wait for the operation to complete and
       then reschedule and continue as normal. (For example, this is what
       :func:`trio.run_in_worker_thread` does if cancellation is disabled.)
       The other possibility is that the ``abort_fn`` does succeed in
       cancelling the operation, but for some reason isn't able to report that
       right away. (Example: on Windows, it's possible to request that an
       async ("overlapped") I/O operation be cancelled, but this request is
       *also* asynchronous – you don't find out until later whether the
       operation was actually cancelled or not.)  To report a delayed
       cancellation, then you should reschedule the task yourself, and call
       the ``raise_cancel`` callback passed to ``abort_fn`` to raise a
       :exc:`~trio.Cancelled` (or possibly :exc:`KeyboardInterrupt`) exception
       into this task. Either of the approaches sketched below can work::

          # Option 1:
          # Catch the exception from raise_cancel and inject it into the task.
          # (This is what trio does automatically for you if you return
          # Abort.SUCCEEDED.)
          trio.hazmat.reschedule(task, Result.capture(raise_cancel))

          # Option 2:
          # wait to be woken by "someone", and then decide whether to raise
          # the error from inside the task.
          outer_raise_cancel = None
          def abort(inner_raise_cancel):
              nonlocal outer_raise_cancel
              outer_raise_cancel = inner_raise_cancel
              TRY_TO_CANCEL_OPERATION()
              return trio.hazmat.Abort.FAILED
          await yield_indefinitely(abort)
          if OPERATION_WAS_SUCCESSFULLY_CANCELLED:
              # raises the error
              outer_raise_cancel()

       In any case it's guaranteed that we only call the ``abort_fn`` at most
       once per call to :func:`yield_indefinitely`.

    .. warning::

       If your ``abort_fn`` raises an error, or returns any value other than
       :data:`Abort.SUCCEEDED` or :data:`Abort.FAILED`, then trio will crash
       violently. Be careful! Similarly, it is entirely possible to deadlock a
       trio program by failing to reschedule a blocked task, or cause havoc by
       calling :func:`reschedule` too many times. Remember what we said up
       above about how you should use a higher-level API if at all possible?

    """
    return (yield (yield_indefinitely, abort_fn)).unwrap()
