from contextlib import contextmanager

from . import _core

__all__ = ["sleep_until", "sleep", "move_on_after", "fail_at", "fail_after",
           "TooSlowError"]

async def sleep_until(deadline):
    with _core.move_on_at(deadline):
        await _core.yield_indefinitely(lambda: _core.Abort.SUCCEEDED)

async def sleep(seconds):
    if seconds < 0:
        raise ValueError("duration must be non-negative")
    if seconds == 0:
        await _core.yield_briefly()
    else:
        await sleep_until(_core.current_time() + seconds)

# pass float("inf") if you want to disable deadline
def move_on_after(seconds):
    if seconds < 0:
        raise ValueError("timeout must be non-negative")
    return _core.move_on_at(_core.current_time() + seconds)

class TooSlowError(Exception):
    pass

@contextmanager
def fail_at(deadline):
    try:
        with move_on_at(deadline) as timeout:
            yield timeout
    finally:
        if timeout.raised:
            raise TooSlowError

@contextmanager
def fail_after(seconds):
    try:
        with move_on_after(seconds) as timeout:
            yield timeout
    finally:
        if timeout.raised:
            raise TooSlowError
