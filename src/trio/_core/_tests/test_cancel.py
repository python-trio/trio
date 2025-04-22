# there's tons of cancellation testing in test_run, but that file is 3k lines long already...

from math import inf

import pytest

import trio
from trio import Cancelled
from trio.lowlevel import current_task
from trio.testing import RaisesGroup


async def test_cancel_reason() -> None:
    with trio.CancelScope() as cs:
        cs.cancel(reason="hello")
        with pytest.raises(
            Cancelled,
            match=rf"^Cancelled due to explicit with reason 'hello' from task {current_task()!r}$",
        ):
            await trio.lowlevel.checkpoint()

    with trio.CancelScope(deadline=-inf) as cs:
        with pytest.raises(Cancelled, match=r"^Cancelled due to deadline"):
            await trio.lowlevel.checkpoint()

    with trio.CancelScope() as cs:
        cs.deadline = -inf
        with pytest.raises(
            Cancelled,
            # FIXME: ??
            match=r"^Cancelled due to explicit from task None",
        ):
            await trio.lowlevel.checkpoint()


async def test_cancel_reason_nursery() -> None:
    async def failing_task(task_status: trio.TaskStatus[trio.lowlevel.Task]) -> None:
        task_status.started(current_task())
        raise ValueError

    async def cancelled_task(
        fail_task: trio.lowlevel.Task, task_status: trio.TaskStatus
    ) -> None:
        task_status.started()
        with pytest.raises(
            Cancelled, match=rf"^Cancelled due to nursery from task {fail_task!r}$"
        ):
            await trio.sleep_forever()
        raise TypeError

    with RaisesGroup(ValueError, TypeError):
        async with trio.open_nursery() as nursery:
            fail_task = await nursery.start(failing_task)
            await nursery.start(cancelled_task, fail_task)


async def test_cancel_reason_nursery2() -> None:
    async def failing_task(
        event: trio.Event, task_status: trio.TaskStatus[trio.lowlevel.Task]
    ) -> None:
        task_status.started(current_task())
        await event.wait()
        raise ValueError

    async def cancelled_task(
        fail_task: trio.lowlevel.Task, task_status: trio.TaskStatus
    ) -> None:
        task_status.started()
        with pytest.raises(
            Cancelled, match=rf"^Cancelled due to nursery from task {fail_task!r}$"
        ):
            await trio.sleep_forever()
        raise TypeError

    with RaisesGroup(ValueError, TypeError):
        async with trio.open_nursery() as nursery:
            event = trio.Event()
            fail_task = await nursery.start(failing_task, event)
            await nursery.start(cancelled_task, fail_task)
            event.set()


async def test_cancel_reason_not_overwritten() -> None:
    with trio.CancelScope() as cs:
        cs.cancel()
        with pytest.raises(Cancelled, match=r"^Cancelled due to explicit"):
            await trio.lowlevel.checkpoint()
        cs.deadline = -inf
        with pytest.raises(Cancelled, match=r"^Cancelled due to explicit"):
            await trio.lowlevel.checkpoint()


async def test_cancel_reason_not_overwritten_2() -> None:
    # TODO: broken, see earlier test
    with trio.CancelScope() as cs:
        cs.deadline = -inf
        with pytest.raises(Cancelled, match=r"^Cancelled due to explicit"):
            await trio.lowlevel.checkpoint()
        cs.cancel()
        with pytest.raises(Cancelled, match=r"^Cancelled due to explicit"):
            await trio.lowlevel.checkpoint()
