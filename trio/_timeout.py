from contextlib import contextmanager

from . import _core

__all__ = ["cancel_after", "sleep_until", "sleep"]

# pass float("inf") if you want to disable deadline
def cancel_after(seconds):
    if seconds < 0:
        raise ValueError("timeout must be non-negative")
    return _core.cancel_at(_core.current_time() + seconds)

async def sleep_until(deadline):
    with _core.cancel_at(deadline):
        await _core.yield_indefinitely(lambda: _core.Abort.SUCCEEDED)

async def sleep(seconds):
    if seconds < 0:
        raise ValueError("duration must be non-negative")
    if seconds == 0:
        await _core.yield_briefly()
    else:
        await sleep_until(_core.current_time() + seconds)
