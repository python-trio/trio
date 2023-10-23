"""These tests are for fixing https://github.com/python-trio/trio/issues/2611"""
import sys

import pytest

import trio
from trio import TaskStatus

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup, ExceptionGroup


async def raise_before(*, task_status: TaskStatus[None]) -> None:
    raise ValueError


async def raise_after_started(*, task_status: TaskStatus[None]) -> None:
    task_status.started()
    raise ValueError


async def raise_custom_exception_group_before(*, task_status: TaskStatus[None]) -> None:
    raise ExceptionGroup("my group", [ValueError()])


# interestingly enough, this never did a double wrap
async def test_strict_before_started() -> None:
    with pytest.raises(BaseExceptionGroup) as exc:
        async with trio.open_nursery(strict_exception_groups=True) as nursery:
            await nursery.start(raise_before)
    assert len(exc.value.exceptions) == 1
    assert isinstance(exc.value.exceptions[0], ValueError)


async def test_no_strict_before_started() -> None:
    with pytest.raises(ValueError):
        async with trio.open_nursery(strict_exception_groups=False) as nursery:
            await nursery.start(raise_before)


async def test_strict_after_started() -> None:
    with pytest.raises(BaseExceptionGroup) as exc:
        async with trio.open_nursery(strict_exception_groups=True) as nursery:
            await nursery.start(raise_after_started)
    assert len(exc.value.exceptions) == 1
    assert isinstance(exc.value.exceptions[0], ValueError)


async def test_no_strict_after_started() -> None:
    with pytest.raises(ValueError):
        async with trio.open_nursery(strict_exception_groups=False) as nursery:
            await nursery.start(raise_after_started)


# it was only when run from `trio.run` that the double wrapping happened
def test_trio_run_strict_before_started() -> None:
    async def main() -> None:
        async with trio.open_nursery() as nursery:
            await nursery.start(raise_before)

    with pytest.raises(BaseExceptionGroup) as exc:
        trio.run(main, strict_exception_groups=True)
    assert len(exc.value.exceptions) == 1
    assert isinstance(exc.value.exceptions[0], ValueError)


def test_trio_run_strict_after_started() -> None:
    async def main() -> None:
        async with trio.open_nursery() as nursery:
            await nursery.start(raise_after_started)

    with pytest.raises(BaseExceptionGroup) as exc:
        trio.run(main, strict_exception_groups=True)
    assert len(exc.value.exceptions) == 1
    assert isinstance(exc.value.exceptions[0], ValueError)


def test_trio_run_no_strict_before_started() -> None:
    async def main() -> None:
        async with trio.open_nursery() as nursery:
            await nursery.start(raise_before)

    with pytest.raises(ValueError):
        trio.run(main, strict_exception_groups=False)


def test_trio_run_no_strict_after_started() -> None:
    async def main() -> None:
        async with trio.open_nursery() as nursery:
            await nursery.start(raise_after_started)

    with pytest.raises(ValueError):
        trio.run(main, strict_exception_groups=False)


# TODO: this shouldn't doublewrap, but should it modify the exception/traceback in any way?
def test_trio_run_strict_exceptiongroup_before_started() -> None:
    async def main() -> None:
        async with trio.open_nursery() as nursery:
            await nursery.start(raise_custom_exception_group_before)

    with pytest.raises(BaseExceptionGroup) as exc:
        trio.run(main, strict_exception_groups=True)
    assert len(exc.value.exceptions) == 1
    assert isinstance(exc.value.exceptions[0], ValueError)
