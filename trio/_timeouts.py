from contextlib import contextmanager

from . import _core

__all__ = [
    "move_on_after", "sleep_until", "sleep",
    "fail_at", "fail_after", "TooSlowError",
]

def move_on_after(seconds):
    if seconds < 0:
        raise ValueError("timeout must be non-negative")
    return move_on_at(_core.current_time() + seconds)

async def sleep_until(deadline):
    with move_on_at(deadline):
        await _core.yield_indefinitely(lambda: _core.Abort.SUCCEEDED)

async def sleep(seconds):
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
        if scope.cancel_caught:
            raise TooSlowError

def fail_after(seconds):
    if seconds < 0:
        raise ValueError("timeout must be non-negative")
    return fail_at(_core.current_time() + seconds)
