from contextlib import contextmanager

from . import _core

__all__ = [
    "move_on_at",
    "move_on_after",
    "sleep_forever",
    "sleep_until",
    "sleep",
    "fail_at",
    "fail_after",
    "shield_during_cleanup",
    "TooSlowError",
]


def move_on_at(deadline, *, grace_period=0):
    """Use as a context manager to create a cancel scope with the given
    absolute deadline.

    Args:
      deadline (float): The deadline.
      grace_period (float): The number of additional seconds to permit
          code in :func:`shield_during_cleanup` blocks within this
          scope to run after the deadline expires.

    Raises:
      ValueError: if ``grace_period`` is less than zero

    """
    if grace_period < 0:
        raise ValueError("grace_period must be non-negative")
    return _core.CancelScope(
        deadline=deadline, cleanup_deadline=deadline + grace_period
    )


def move_on_after(seconds, *, grace_period=0):
    """Use as a context manager to create a cancel scope whose deadline is
    set to now + *seconds*.

    Args:
      seconds (float): The timeout.
      grace_period (float): The number of additional seconds to permit
          code in :func:`shield_during_cleanup` blocks within this
          scope to run after the timeout expires.

    Raises:
      ValueError: if timeout or grace_period is less than zero.

    """

    if seconds < 0:
        raise ValueError("timeout must be non-negative")
    return move_on_at(
        _core.current_time() + seconds, grace_period=grace_period
    )


async def sleep_forever():
    """Pause execution of the current task forever (or until cancelled).

    Equivalent to calling ``await sleep(math.inf)``.

    """
    await _core.wait_task_rescheduled(lambda _: _core.Abort.SUCCEEDED)


async def sleep_until(deadline):
    """Pause execution of the current task until the given time.

    The difference between :func:`sleep` and :func:`sleep_until` is that the
    former takes a relative time and the latter takes an absolute time.

    Args:
        deadline (float): The time at which we should wake up again. May be in
            the past, in which case this function yields but does not block.

    """
    with move_on_at(deadline):
        await sleep_forever()


async def sleep(seconds):
    """Pause execution of the current task for the given number of seconds.

    Args:
        seconds (float): The number of seconds to sleep. May be zero to
            insert a checkpoint without actually blocking.

    Raises:
        ValueError: if *seconds* is negative.

    """
    if seconds < 0:
        raise ValueError("duration must be non-negative")
    if seconds == 0:
        await _core.checkpoint()
    else:
        await sleep_until(_core.current_time() + seconds)


class TooSlowError(Exception):
    """Raised by :func:`fail_after` and :func:`fail_at` if the timeout
    expires.

    """
    pass


@contextmanager
def fail_at(deadline, *, grace_period=0):
    """Creates a cancel scope with the given deadline, and raises an error if it
    is actually cancelled.

    This function and :func:`move_on_at` are similar in that both create a
    cancel scope with a given absolute deadline, and if the deadline expires
    then both will cause :exc:`Cancelled` to be raised within the scope. The
    difference is that when the :exc:`Cancelled` exception reaches
    :func:`move_on_at`, it's caught and discarded. When it reaches
    :func:`fail_at`, then it's caught and :exc:`TooSlowError` is raised in its
    place.

    Raises:
      TooSlowError: if a :exc:`Cancelled` exception is raised in this scope
        and caught by the context manager.
      ValueError: if *grace_period* is less than zero.

    """

    with move_on_at(deadline, grace_period=grace_period) as scope:
        yield scope
    if scope.cancelled_caught:
        raise TooSlowError


def fail_after(seconds, *, grace_period=0):
    """Creates a cancel scope with the given timeout, and raises an error if
    it is actually cancelled.

    This function and :func:`move_on_after` are similar in that both create a
    cancel scope with a given timeout, and if the timeout expires then both
    will cause :exc:`Cancelled` to be raised within the scope. The difference
    is that when the :exc:`Cancelled` exception reaches :func:`move_on_after`,
    it's caught and discarded. When it reaches :func:`fail_after`, then it's
    caught and :exc:`TooSlowError` is raised in its place.

    Raises:
      TooSlowError: if a :exc:`Cancelled` exception is raised in this scope
        and caught by the context manager.
      ValueError: if *seconds* or *grace_period* is less than zero.

    """
    if seconds < 0:
        raise ValueError("timeout must be non-negative")
    return fail_at(_core.current_time() + seconds, grace_period=grace_period)


def shield_during_cleanup():
    """Use as a context manager to mark code that should be allowed to
    run for a bit longer after a cancel scope that surrounds it becomes
    cancelled.

    This is intended for use with cleanup code that might run while a
    :exc:`~trio.Cancelled` exception is propagating (e.g., in
    ``finally`` blocks or ``__aexit__`` handlers) for which an orderly
    shutdown requires blocking. It can also be used to guard
    non-cleanup code that is likely to be able to run to completion in
    a modest amount of time, where the extra time taken to propagate
    the cancellation is less disruptive than a forced immediate
    shutdown would be.

    The exact amount of additional time allowed is specified by the
    ``grace_period`` argument to the :meth:`~trio.CancelScope.cancel`
    call that caused the cancellation; if the cancellation occurred
    due to deadline expiry, the grace period is as was specified when
    creating the cancel scope that became cancelled (via
    :func:`move_on_after` or similar) or as implied by the setting of
    its underlying :attr:`CancelScope.cleanup_deadline` attribute.

    The default grace period is *zero*, and code that uses
    :func:`shield_during_cleanup` must still be prepared for
    a possible cancellation.  Use a cancel scope with the
    :attr:`~CancelScope.shield` attribute set to :data:`True` if
    you really need to definitely not be interrupted.

    """
    return _core.CancelScope(shield_during_cleanup=True)
