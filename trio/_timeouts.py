from contextlib import contextmanager

from . import _core

__all__ = [
    "move_on_at", "move_on_after", "sleep_forever", "sleep_until", "sleep",
    "fail_at", "fail_after", "TooSlowError",
]

def move_on_at(deadline):
    """Returns a context manager which opens a cancel scope with the given
    deadline.

    """
    return _core.open_cancel_scope(deadline=deadline)

def move_on_after(seconds):
    if seconds < 0:
        raise ValueError("timeout must be non-negative")
    return move_on_at(_core.current_time() + seconds)

async def sleep_forever():
    """Pause execution of the current task forever (or until cancelled).

    Equivalent to calling ``await sleep(math.inf)``.

    """
    await _core.yield_indefinitely(lambda _: _core.Abort.SUCCEEDED)

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
            insert a yield point without actually blocking.

    Raises:
        ValueError: if *seconds* is negative.

    """
    if seconds < 0:
        raise ValueError("duration must be non-negative")
    if seconds == 0:
        await _core.yield_briefly()
    else:
        await sleep_until(_core.current_time() + seconds)

class TooSlowError(Exception):
    pass

@contextmanager
def fail_at(deadline):
    try:
        with move_on_at(deadline) as scope:
            yield scope
    finally:
        if scope.cancelled_caught:
            raise TooSlowError

def fail_after(seconds):
    if seconds < 0:
        raise ValueError("timeout must be non-negative")
    return fail_at(_core.current_time() + seconds)
