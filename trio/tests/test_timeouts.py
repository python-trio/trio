import pytest
import time

from .. import _core
from .._timeouts import *

async def check_takes_about(f, expected_dur):
    start = time.monotonic()
    result = await _core.Result.acapture(f)
    dur = time.monotonic() - start
    # In practice on my laptop I get numbers like 1.003, so 1.2 seems pretty
    # conservative. On appveyor it's usually 1.0, so the <= is important.
    print(dur / expected_dur)
    assert 1 <= (dur / expected_dur) < 1.2
    return result.unwrap()

async def test_sleep():
    async def sleep_025_1():
        await sleep_until(_core.current_time() + 0.25)
    await check_takes_about(sleep_025_1, 0.25)

    async def sleep_025_2():
        await sleep(0.25)
    await check_takes_about(sleep_025_2, 0.25)

    with pytest.raises(ValueError):
        await sleep(-1)

    await sleep(0)
    # This also serves as a test of the trivial move_on_at
    with move_on_at(_core.current_time()):
        with pytest.raises(_core.Cancelled):
            await sleep(0)


async def test_move_on_after():
    with pytest.raises(ValueError):
        with move_on_after(-1):
            pass  # pragma: no cover

    async def sleep_025_3():
        with move_on_after(0.25):
            await sleep(100)
    await check_takes_about(sleep_025_3, 0.25)


async def test_fail():
    async def sleep_025_4():
        with fail_at(_core.current_time() + 0.25):
            await sleep(100)
    with pytest.raises(TooSlowError):
        await check_takes_about(sleep_025_4, 0.25)

    with fail_at(_core.current_time() + 100):
        await sleep(0)

    async def sleep_025_5():
        with fail_after(0.25):
            await sleep(100)
    with pytest.raises(TooSlowError):
        await check_takes_about(sleep_025_5, 0.25)

    with fail_after(100):
        await sleep(0)
