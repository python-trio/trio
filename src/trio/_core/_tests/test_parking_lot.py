from __future__ import annotations

from typing import TypeVar

import pytest

import trio.lowlevel
from trio.testing import Matcher, RaisesGroup

from ... import _core
from ...testing import wait_all_tasks_blocked
from .._parking_lot import ParkingLot
from .tutil import check_sequence_matches

T = TypeVar("T")


async def test_parking_lot_basic() -> None:
    record = []

    async def waiter(i: int, lot: ParkingLot) -> None:
        record.append(f"sleep {i}")
        await lot.park()
        record.append(f"wake {i}")

    async with _core.open_nursery() as nursery:
        lot = ParkingLot()
        assert not lot
        assert len(lot) == 0
        assert lot.statistics().tasks_waiting == 0
        for i in range(3):
            nursery.start_soon(waiter, i, lot)
        await wait_all_tasks_blocked()
        assert len(record) == 3
        assert bool(lot)
        assert len(lot) == 3
        assert lot.statistics().tasks_waiting == 3
        lot.unpark_all()
        assert lot.statistics().tasks_waiting == 0
        await wait_all_tasks_blocked()
        assert len(record) == 6

    check_sequence_matches(
        record,
        [{"sleep 0", "sleep 1", "sleep 2"}, {"wake 0", "wake 1", "wake 2"}],
    )

    async with _core.open_nursery() as nursery:
        record = []
        for i in range(3):
            nursery.start_soon(waiter, i, lot)
            await wait_all_tasks_blocked()
        assert len(record) == 3
        for _ in range(3):
            lot.unpark()
            await wait_all_tasks_blocked()
        # 1-by-1 wakeups are strict FIFO
        assert record == [
            "sleep 0",
            "sleep 1",
            "sleep 2",
            "wake 0",
            "wake 1",
            "wake 2",
        ]

    # It's legal (but a no-op) to try and unpark while there's nothing parked
    lot.unpark()
    lot.unpark(count=1)
    lot.unpark(count=100)

    # Check unpark with count
    async with _core.open_nursery() as nursery:
        record = []
        for i in range(3):
            nursery.start_soon(waiter, i, lot)
            await wait_all_tasks_blocked()
        lot.unpark(count=2)
        await wait_all_tasks_blocked()
        check_sequence_matches(
            record,
            ["sleep 0", "sleep 1", "sleep 2", {"wake 0", "wake 1"}],
        )
        lot.unpark_all()

    with pytest.raises(
        ValueError,
        match=r"^Cannot pop a non-integer number of tasks\.$",
    ):
        lot.unpark(count=1.5)


async def cancellable_waiter(
    name: T,
    lot: ParkingLot,
    scopes: dict[T, _core.CancelScope],
    record: list[str],
) -> None:
    with _core.CancelScope() as scope:
        scopes[name] = scope
        record.append(f"sleep {name}")
        try:
            await lot.park()
        except _core.Cancelled:
            record.append(f"cancelled {name}")
        else:
            record.append(f"wake {name}")


async def test_parking_lot_cancel() -> None:
    record: list[str] = []
    scopes: dict[int, _core.CancelScope] = {}

    async with _core.open_nursery() as nursery:
        lot = ParkingLot()
        nursery.start_soon(cancellable_waiter, 1, lot, scopes, record)
        await wait_all_tasks_blocked()
        nursery.start_soon(cancellable_waiter, 2, lot, scopes, record)
        await wait_all_tasks_blocked()
        nursery.start_soon(cancellable_waiter, 3, lot, scopes, record)
        await wait_all_tasks_blocked()
        assert len(record) == 3

        scopes[2].cancel()
        await wait_all_tasks_blocked()
        assert len(record) == 4
        lot.unpark_all()
        await wait_all_tasks_blocked()
        assert len(record) == 6

    check_sequence_matches(
        record,
        ["sleep 1", "sleep 2", "sleep 3", "cancelled 2", {"wake 1", "wake 3"}],
    )


async def test_parking_lot_repark() -> None:
    record: list[str] = []
    scopes: dict[int, _core.CancelScope] = {}
    lot1 = ParkingLot()
    lot2 = ParkingLot()

    with pytest.raises(TypeError):
        lot1.repark([])  # type: ignore[arg-type]

    async with _core.open_nursery() as nursery:
        nursery.start_soon(cancellable_waiter, 1, lot1, scopes, record)
        await wait_all_tasks_blocked()
        nursery.start_soon(cancellable_waiter, 2, lot1, scopes, record)
        await wait_all_tasks_blocked()
        nursery.start_soon(cancellable_waiter, 3, lot1, scopes, record)
        await wait_all_tasks_blocked()
        assert len(record) == 3

        assert len(lot1) == 3
        lot1.repark(lot2)
        assert len(lot1) == 2
        assert len(lot2) == 1
        lot2.unpark_all()
        await wait_all_tasks_blocked()
        assert len(record) == 4
        assert record == ["sleep 1", "sleep 2", "sleep 3", "wake 1"]

        lot1.repark_all(lot2)
        assert len(lot1) == 0
        assert len(lot2) == 2

        scopes[2].cancel()
        await wait_all_tasks_blocked()
        assert len(lot2) == 1
        assert record == [
            "sleep 1",
            "sleep 2",
            "sleep 3",
            "wake 1",
            "cancelled 2",
        ]

        lot2.unpark_all()
        await wait_all_tasks_blocked()
        assert record == [
            "sleep 1",
            "sleep 2",
            "sleep 3",
            "wake 1",
            "cancelled 2",
            "wake 3",
        ]


async def test_parking_lot_repark_with_count() -> None:
    record: list[str] = []
    scopes: dict[int, _core.CancelScope] = {}
    lot1 = ParkingLot()
    lot2 = ParkingLot()
    async with _core.open_nursery() as nursery:
        nursery.start_soon(cancellable_waiter, 1, lot1, scopes, record)
        await wait_all_tasks_blocked()
        nursery.start_soon(cancellable_waiter, 2, lot1, scopes, record)
        await wait_all_tasks_blocked()
        nursery.start_soon(cancellable_waiter, 3, lot1, scopes, record)
        await wait_all_tasks_blocked()
        assert len(record) == 3

        assert len(lot1) == 3
        assert len(lot2) == 0
        lot1.repark(lot2, count=2)
        assert len(lot1) == 1
        assert len(lot2) == 2
        while lot2:
            lot2.unpark()
            await wait_all_tasks_blocked()
        assert record == [
            "sleep 1",
            "sleep 2",
            "sleep 3",
            "wake 1",
            "wake 2",
        ]
        lot1.unpark_all()


async def test_parking_lot_breaker_basic() -> None:
    lot = ParkingLot()
    task = trio.lowlevel.current_task()

    with pytest.raises(
        RuntimeError,
        match="Attempted to remove task as breaker for a lot it is not registered for",
    ):
        trio.lowlevel.remove_parking_lot_breaker(task, lot)
    trio.lowlevel.add_parking_lot_breaker(task, lot)
    trio.lowlevel.add_parking_lot_breaker(task, lot)
    trio.lowlevel.remove_parking_lot_breaker(task, lot)
    trio.lowlevel.remove_parking_lot_breaker(task, lot)

    with pytest.raises(
        RuntimeError,
        match="Attempted to remove task as breaker for a lot it is not registered for",
    ):
        trio.lowlevel.remove_parking_lot_breaker(task, lot)

    lot.break_lot()
    assert lot.broken_by == task


async def test_parking_lot_breaker() -> None:
    async def bad_parker(lot: ParkingLot, scope: _core.CancelScope) -> None:
        trio.lowlevel.add_parking_lot_breaker(trio.lowlevel.current_task(), lot)
        with scope:
            await trio.sleep_forever()

    lot = ParkingLot()
    cs = _core.CancelScope()

    # check that parked task errors
    with RaisesGroup(
        Matcher(_core.BrokenResourceError, match="^Parking lot broken by"),
    ):
        async with _core.open_nursery() as nursery:
            nursery.start_soon(bad_parker, lot, cs)
            await wait_all_tasks_blocked()

            nursery.start_soon(lot.park)
            await wait_all_tasks_blocked()

            cs.cancel()

    # check that trying to park in brokena lot errors
    with pytest.raises(_core.BrokenResourceError):
        await lot.park()


async def test_parking_lot_weird() -> None:
    """break a parking lot, where the breakee is parked. Doing this is weird, but should probably be supported??
    Although the message makes less sense"""

    async def return_me_and_park(
        lot: ParkingLot,
        *,
        task_status: _core.TaskStatus[_core.Task] = trio.TASK_STATUS_IGNORED,
    ) -> None:
        task_status.started(_core.current_task())
        await lot.park()

    lot = ParkingLot()
    with RaisesGroup(Matcher(_core.BrokenResourceError, match="Parking lot broken by")):
        async with _core.open_nursery() as nursery:
            task = await nursery.start(return_me_and_park, lot)
            lot.break_lot(task)
