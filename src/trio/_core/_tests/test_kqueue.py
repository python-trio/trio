"""Tests for the kqueue-specific lowlevel API (wait_kevent)."""

from __future__ import annotations

import select
import time

import pytest

import trio
from trio.testing import wait_all_tasks_blocked

pytestmark = pytest.mark.skipif(
    not hasattr(select, "kqueue"),
    reason="kqueue platforms only",
)


async def test_wait_kevent_timer() -> None:
    # Basic test of trio.lowlevel.wait_kevent() - a 20ms timer.
    event = await trio.lowlevel.wait_kevent(1, select.KQ_FILTER_TIMER, data=20)
    assert event.ident == 1
    assert event.filter == select.KQ_FILTER_TIMER
    assert event.data >= 1


async def test_wait_kevent_cancellation_deregisters() -> None:
    # Tests that cancelling trio.lowlevel.wait_kevent() actually does unregister
    # the event (by registering a new one and checking that it doesn't raise
    # BusyResourceError).
    with trio.move_on_after(0.05) as scope:
        await trio.lowlevel.wait_kevent(2, select.KQ_FILTER_TIMER, data=10_000)
    assert scope.cancelled_caught
    event = await trio.lowlevel.wait_kevent(2, select.KQ_FILTER_TIMER, data=20)
    assert event.data >= 1


async def test_wait_kevent_busy_loser_arms_nothing() -> None:
    # Tests that calling trio.lowlevel.wait_kevent() when an existing wait for
    # that (ident, filter) pair is in progress does not affect the existing
    # waiter (unlike the old wait_kevent API, where the caller would do the
    # OS registration so could modify parameters of an existing wait).
    # The test works by waiting for a 200ms timer then, during that, waiting
    # for a 10ms timer.
    result: select.kevent | None = None

    async def waiter() -> None:
        nonlocal result
        result = await trio.lowlevel.wait_kevent(
            3,
            select.KQ_FILTER_TIMER,
            data=200,
        )

    start = time.monotonic()
    async with trio.open_nursery() as nursery:
        nursery.start_soon(waiter)
        await wait_all_tasks_blocked()
        with pytest.raises(trio.BusyResourceError):
            await trio.lowlevel.wait_kevent(3, select.KQ_FILTER_TIMER, data=10)
    assert result is not None
    # Kernel timers never fire early, so this only fails if the loser's
    # 10ms registration replaced the winner's 200ms one.
    assert time.monotonic() - start >= 0.15


async def test_wait_kevent_deprecated_abort_func() -> None:
    # Tests that the old deprecated API for trio.lowlevel.wait_kevent() still
    # works. This is the case where the wait is not cancelled.
    kq = trio.lowlevel.current_kqueue()
    kq.control(
        [
            select.kevent(
                4,
                select.KQ_FILTER_TIMER,
                select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                0,
                20,
            ),
        ],
        0,
    )

    def abort(_: object) -> trio.lowlevel.Abort:
        kq.control([select.kevent(4, select.KQ_FILTER_TIMER, select.KQ_EV_DELETE)], 0)
        return trio.lowlevel.Abort.SUCCEEDED

    with pytest.deprecated_call():
        event = await trio.lowlevel.wait_kevent(4, select.KQ_FILTER_TIMER, abort)
    assert event.ident == 4
    assert event.data >= 1


async def test_wait_kevent_deprecated_abort_func_cancel() -> None:
    # Tests that the old deprecated API for trio.lowlevel.wait_kevent() still
    # works. This is the case where the wait is cancelled (in particular, it
    # checks that a new wait on the same (ident, filter) pair can be started
    # immediately afterwards).
    kq = trio.lowlevel.current_kqueue()
    kq.control(
        [
            select.kevent(
                5,
                select.KQ_FILTER_TIMER,
                select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                0,
                10_000,
            ),
        ],
        0,
    )
    aborted = False

    def abort(_: object) -> trio.lowlevel.Abort:
        nonlocal aborted
        aborted = True
        kq.control([select.kevent(5, select.KQ_FILTER_TIMER, select.KQ_EV_DELETE)], 0)
        return trio.lowlevel.Abort.SUCCEEDED

    with trio.move_on_after(0.05) as scope:
        with pytest.deprecated_call():
            await trio.lowlevel.wait_kevent(5, select.KQ_FILTER_TIMER, abort)
    assert scope.cancelled_caught
    assert aborted
    event = await trio.lowlevel.wait_kevent(5, select.KQ_FILTER_TIMER, data=20)
    assert event.data >= 1
