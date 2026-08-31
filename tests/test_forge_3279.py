"""Regression test for verbose tracebacks in trio internal frames.

When a Cancelled exception propagates through trio internals (parking lot,
traps, outcome unwrap), the traceback contains many unhelpful internal frames.
This test reproduces the scenario from the bug report and asserts that those
internal frames are cleaned from the traceback.
"""

import traceback as tb_mod

import pytest
import trio
import trio.testing


def _tb_filenames(exc: BaseException) -> list[str]:
    """Return the list of source filenames in an exception's traceback."""
    names = []
    tb = exc.__traceback__
    while tb is not None:
        names.append(tb.tb_frame.f_code.co_filename)
        tb = tb.tb_next
    return names


def _has_frame_from(exc: BaseException, *module_substrings: str) -> bool:
    """Check whether any frame in exc's traceback comes from a file whose
    path contains one of the given substrings."""
    for fname in _tb_filenames(exc):
        for sub in module_substrings:
            if sub in fname:
                return True
    return False


async def test_fail_after_cancelled_traceback_cleaned() -> None:
    """Reproduce the bug-report scenario and verify internal frames are removed
    from the Cancelled exception's traceback."""
    cl = trio.CapacityLimiter(1)

    async def borrower() -> None:
        await cl.acquire()
        await trio.sleep_forever()

    async def main() -> None:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(borrower)
            await trio.testing.wait_all_tasks_blocked()

            with trio.fail_after(1):
                async with cl:
                    pass

    with pytest.raises(BaseExceptionGroup) as exc_info:
        await main()

    group = exc_info.value
    # The group should contain a TooSlowError
    too_slow_errors = group.exceptions
    assert len(too_slow_errors) == 1
    too_slow = too_slow_errors[0]
    assert isinstance(too_slow, trio.TooSlowError)

    # The TooSlowError's __context__ should be the Cancelled exception
    cancelled = too_slow.__context__
    assert isinstance(cancelled, trio.Cancelled)

    # The Cancelled exception's traceback should NOT contain frames from
    # trio's internal trap/parking-lot/outcome machinery.  These are
    # implementation details that add noise without helping the user
    # understand why their code was cancelled.
    assert not _has_frame_from(
        cancelled,
        "_traps.py",  # wait_task_rescheduled
        "_parking_lot.py",  # ParkingLot.park
        "outcome",  # Outcome.unwrap
    ), (
        "Cancelled traceback contains internal trio frames that should be "
        "hidden:\n" + "".join(tb_mod.format_exception(cancelled))
    )
