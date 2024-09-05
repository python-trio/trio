import time
from typing import Awaitable, Callable, Protocol, TypeVar

import outcome
import pytest

import trio

from .. import _core
from .._core._tests.tutil import slow
from .._timeouts import (
    TooSlowError,
    fail_after,
    fail_at,
    move_on_after,
    move_on_at,
    sleep,
    sleep_forever,
    sleep_until,
)
from ..testing import assert_checkpoints

T = TypeVar("T")


async def check_takes_about(f: Callable[[], Awaitable[T]], expected_dur: float) -> T:
    start = time.perf_counter()
    result = await outcome.acapture(f)
    dur = time.perf_counter() - start
    print(dur / expected_dur)
    # 1.5 is an arbitrary fudge factor because there's always some delay
    # between when we become eligible to wake up and when we actually do. We
    # used to sleep for 0.05, and regularly observed overruns of 1.6x on
    # Appveyor, and then started seeing overruns of 2.3x on Travis's macOS, so
    # now we bumped up the sleep to 1 second, marked the tests as slow, and
    # hopefully now the proportional error will be less huge.
    #
    # We also also for durations that are a hair shorter than expected. For
    # example, here's a run on Windows where a 1.0 second sleep was measured
    # to take 0.9999999999999858 seconds:
    #   https://ci.appveyor.com/project/njsmith/trio/build/1.0.768/job/3lbdyxl63q3h9s21
    # I believe that what happened here is that Windows's low clock resolution
    # meant that our calls to time.monotonic() returned exactly the same
    # values as the calls inside the actual run loop, but the two subtractions
    # returned slightly different values because the run loop's clock adds a
    # random floating point offset to both times, which should cancel out, but
    # lol floating point we got slightly different rounding errors. (That
    # value above is exactly 128 ULPs below 1.0, which would make sense if it
    # started as a 1 ULP error at a different dynamic range.)
    assert (1 - 1e-8) <= (dur / expected_dur) < 1.5

    return result.unwrap()


# How long to (attempt to) sleep for when testing. Smaller numbers make the
# test suite go faster.
TARGET = 1.0


@slow
async def test_sleep() -> None:
    async def sleep_1() -> None:
        await sleep_until(_core.current_time() + TARGET)

    await check_takes_about(sleep_1, TARGET)

    async def sleep_2() -> None:
        await sleep(TARGET)

    await check_takes_about(sleep_2, TARGET)

    with assert_checkpoints():
        await sleep(0)
    # This also serves as a test of the trivial move_on_at
    with move_on_at(_core.current_time()):
        with pytest.raises(_core.Cancelled):
            await sleep(0)


@slow
async def test_move_on_after() -> None:
    async def sleep_3() -> None:
        with move_on_after(TARGET):
            await sleep(100)

    await check_takes_about(sleep_3, TARGET)


class TimeoutScope(Protocol):
    def __call__(self, seconds: float, *, shield: bool) -> trio.CancelScope: ...


@pytest.mark.parametrize("scope", [move_on_after, fail_after])
async def test_context_shields_from_outer(scope: TimeoutScope) -> None:
    with _core.CancelScope() as outer, scope(TARGET, shield=True) as inner:
        outer.cancel()
        try:
            await trio.lowlevel.checkpoint()
        except trio.Cancelled:
            pytest.fail("shield didn't work")
        inner.shield = False
        with pytest.raises(trio.Cancelled):
            await trio.lowlevel.checkpoint()


@slow
async def test_move_on_after_moves_on_even_if_shielded() -> None:
    async def task() -> None:
        with _core.CancelScope() as outer, move_on_after(TARGET, shield=True):
            outer.cancel()
            # The outer scope is cancelled, but this task is protected by the
            # shield, so it manages to get to sleep until deadline is met
            await sleep_forever()

    await check_takes_about(task, TARGET)


@slow
async def test_fail_after_fails_even_if_shielded() -> None:
    async def task() -> None:
        with pytest.raises(TooSlowError), _core.CancelScope() as outer, fail_after(
            TARGET,
            shield=True,
        ):
            outer.cancel()
            # The outer scope is cancelled, but this task is protected by the
            # shield, so it manages to get to sleep until deadline is met
            await sleep_forever()

    await check_takes_about(task, TARGET)


@slow
async def test_fail() -> None:
    async def sleep_4() -> None:
        with fail_at(_core.current_time() + TARGET):
            await sleep(100)

    with pytest.raises(TooSlowError):
        await check_takes_about(sleep_4, TARGET)

    with fail_at(_core.current_time() + 100):
        await sleep(0)

    async def sleep_5() -> None:
        with fail_after(TARGET):
            await sleep(100)

    with pytest.raises(TooSlowError):
        await check_takes_about(sleep_5, TARGET)

    with fail_after(100):
        await sleep(0)


async def test_timeouts_raise_value_error() -> None:
    # deadlines are allowed to be negative, but not delays.
    # neither delays nor deadlines are allowed to be NaN

    nan = float("nan")

    for fun, val in (
        (sleep, -1),
        (sleep, nan),
        (sleep_until, nan),
    ):
        with pytest.raises(
            ValueError,
            match="^(duration|deadline|timeout) must (not )*be (non-negative|NaN)$",
        ):
            await fun(val)

    for cm, val in (
        (fail_after, -1),
        (fail_after, nan),
        (fail_at, nan),
        (move_on_after, -1),
        (move_on_after, nan),
        (move_on_at, nan),
    ):
        with pytest.raises(
            ValueError,
            match="^(duration|deadline|timeout) must (not )*be (non-negative|NaN)$",
        ):
            with cm(val):
                pass  # pragma: no cover


async def test_timeout_deadline_on_entry(mock_clock: _core.MockClock) -> None:
    rcs = move_on_after(5, timeout_from_enter=True)
    assert rcs.relative_deadline == 5

    rcs.shield = True
    assert rcs.shield

    mock_clock.jump(3)
    start = _core.current_time()
    with rcs as cs:
        # This would previously be start+2
        assert cs.deadline == start + 5

    rcs = fail_after(5, timeout_from_enter=True)
    mock_clock.jump(3)
    start = _core.current_time()
    with rcs as cs:
        assert cs.deadline == start + 5

        # check that their shield values are linked
        assert rcs.shield is cs.shield is True

        cs.shield = False
        assert rcs.shield is cs.shield is False

        rcs.shield = True
        assert rcs.shield is cs.shield is True

    # re-entering a _RelativeCancelScope should probably error, but it doesn't *have* to
    with pytest.raises(
        RuntimeError,
        match="^Each _RelativeCancelScope may only be used for a single 'with' block$",
    ):
        with rcs as cs:
            ...


async def test_timeout_deadline_not_on_entry(mock_clock: _core.MockClock) -> None:
    """Test that not setting timeout_from_enter gives a DeprecationWarning and
    retains old behaviour."""
    for cs_gen_fun in (move_on_after, fail_after):
        with pytest.warns(DeprecationWarning, match="issues/2512"):
            rcs = cs_gen_fun(5)
            mock_clock.jump(3)
            with rcs as cs:
                assert rcs.deadline == cs.deadline == _core.current_time() + 2

                rcs.deadline += 1
                assert rcs.deadline == cs.deadline == _core.current_time() + 3

                cs.deadline += 1
                assert rcs.deadline == cs.deadline == _core.current_time() + 4


async def test_transitional_functions_fail() -> None:
    rcs = move_on_after(5, timeout_from_enter=True)
    # these errors are only shown if timeout_from_enter=True

    match_str = "^_RelativeCancelScope does not have `deadline`. You might want `relative_deadline`.$"
    with pytest.raises(AttributeError, match=match_str):
        assert rcs.deadline
    with pytest.raises(AttributeError, match=match_str):
        rcs.deadline = 7

    for prop in "cancelled_caught", "cancel_called":
        match_str = f"_RelativeCancelScope does not have `{prop}`, and cannot have been cancelled before entering."
        with pytest.raises(AttributeError, match=match_str):
            assert getattr(rcs, prop)

    with pytest.raises(
        AttributeError,
        match=match_str[:36] + "cancel`, and cannot be cancelled before entering.",
    ):
        rcs.cancel()

    with rcs:
        match_str = "^_RelativeCancelScope does not have `{}`. You might want to access the entered `CancelScope`.$"
        with pytest.raises(AttributeError, match=match_str.format("deadline")):
            assert rcs.deadline
        with pytest.raises(AttributeError, match=match_str.format("deadline")):
            rcs.deadline = 5
        with pytest.raises(AttributeError, match=match_str.format("cancel")):
            rcs.cancel()
        with pytest.raises(AttributeError, match=match_str.format("cancelled_caught")):
            assert rcs.cancelled_caught
        with pytest.raises(AttributeError, match=match_str.format("cancel_called")):
            assert rcs.cancel_called


async def test_transitional_functions_backwards_compatibility() -> None:
    rcs = move_on_after(5)
    assert rcs.deadline == 5
    rcs.deadline = 7
    assert rcs.cancelled_caught is False
    assert rcs.cancel_called is False
    with pytest.raises(
        RuntimeError,
        match="^It is no longer possible to cancel a relative cancel scope before entering it.$",
    ):
        rcs.cancel()

    # this does not emit any deprecationwarnings because no time has passed
    with rcs as cs:
        assert rcs.deadline == cs.deadline
        assert abs(rcs.deadline - trio.current_time() - 7) < 0.1
        rcs.cancel()
        await trio.lowlevel.checkpoint()  # let the cs get cancelled

    assert rcs.cancelled_caught is cs.cancelled_caught is True
    assert rcs.cancel_called is cs.cancel_called is True
