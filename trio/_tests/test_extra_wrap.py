import pytest

import trio
from trio import TaskStatus


async def startable_fn_which_doesnt_contain_a_nursery(
    raise_before: bool, *, task_status: TaskStatus[None]
) -> None:
    if raise_before:
        print("Something went wrong")
        raise RuntimeError  # this might be wrapped in an ExceptionGroup
    task_status.started()
    raise ValueError  # ...but this will never be wrapped!


async def test_strict_before_started() -> None:
    with pytest.raises(RuntimeError):
        async with trio.open_nursery(strict_exception_groups=True) as nursery:
            await nursery.start(startable_fn_which_doesnt_contain_a_nursery, True)


async def test_no_strict_before_started() -> None:
    with pytest.raises(RuntimeError):
        async with trio.open_nursery(strict_exception_groups=False) as nursery:
            await nursery.start(startable_fn_which_doesnt_contain_a_nursery, True)


async def test_strict_after_started() -> None:
    with pytest.raises(ValueError):
        async with trio.open_nursery(strict_exception_groups=True) as nursery:
            await nursery.start(startable_fn_which_doesnt_contain_a_nursery, False)


async def test_no_strict_after_started() -> None:
    with pytest.raises(ValueError):
        async with trio.open_nursery(strict_exception_groups=False) as nursery:
            await nursery.start(startable_fn_which_doesnt_contain_a_nursery, False)
