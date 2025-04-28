# there's tons of cancellation testing in test_run, but that file is 3k lines long already...

from math import inf

import pytest

import trio
from trio import Cancelled
from trio.lowlevel import current_task
from trio.testing import RaisesGroup

from .test_ki import ki_self


async def test_cancel_reason() -> None:
    with trio.CancelScope() as cs:
        cs.cancel(reason="hello")
        with pytest.raises(
            Cancelled,
            match=rf"^cancelled due to explicit with reason 'hello' from task {current_task()!r}$",
        ):
            await trio.lowlevel.checkpoint()

    with trio.CancelScope(deadline=-inf) as cs:
        with pytest.raises(Cancelled, match=r"^cancelled due to deadline"):
            await trio.lowlevel.checkpoint()

    with trio.CancelScope() as cs:
        cs.deadline = -inf
        with pytest.raises(
            Cancelled,
            match=r"^cancelled due to deadline",
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
            Cancelled,
            match=rf"^cancelled due to nursery with reason 'child task raised exception ValueError\(\)' from task {fail_task!r}$",
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
            Cancelled,
            match=rf"^cancelled due to nursery with reason 'child task raised exception ValueError\(\)' from task {fail_task!r}$",
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
        with pytest.raises(
            Cancelled,
            match=rf"^cancelled due to explicit from task {current_task()!r}$",
        ):
            await trio.lowlevel.checkpoint()
        cs.deadline = -inf
        with pytest.raises(
            Cancelled,
            match=rf"^cancelled due to explicit from task {current_task()!r}$",
        ):
            await trio.lowlevel.checkpoint()


async def test_cancel_reason_not_overwritten_2() -> None:
    with trio.CancelScope() as cs:
        cs.deadline = -inf
        with pytest.raises(Cancelled, match=r"^cancelled due to deadline$"):
            await trio.lowlevel.checkpoint()
        cs.cancel()
        with pytest.raises(Cancelled, match=r"^cancelled due to deadline$"):
            await trio.lowlevel.checkpoint()


async def test_nested_child_source() -> None:
    ev = trio.Event()
    parent_task = current_task()

    async def child() -> None:
        ev.set()
        with pytest.raises(
            Cancelled,
            match=rf"^cancelled due to nursery with reason 'Code block inside nursery contextmanager raised exception ValueError\(\)' from task {parent_task!r}$",
        ):
            await trio.sleep_forever()

    with RaisesGroup(ValueError):
        async with trio.open_nursery() as nursery:
            nursery.start_soon(child)
            await ev.wait()
            raise ValueError


async def test_reason_delayed_ki() -> None:
    # simplified version of test_ki.test_ki_protection_works check #2
    parent_task = current_task()

    async def sleeper(name: str) -> None:
        with pytest.raises(
            Cancelled,
            match=rf"^cancelled due to KeyboardInterrupt from task {parent_task!r}$",
        ):
            while True:
                await trio.lowlevel.checkpoint()

    async def raiser(name: str) -> None:
        ki_self()

    with RaisesGroup(KeyboardInterrupt):
        async with trio.open_nursery() as nursery:
            nursery.start_soon(sleeper, "s1")
            nursery.start_soon(sleeper, "s2")
            nursery.start_soon(trio.lowlevel.enable_ki_protection(raiser), "r1")
            # __aexit__ blocks, and then receives the KI
