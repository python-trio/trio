"""These tests are for fixing https://github.com/python-trio/trio/issues/2611"""
from __future__ import annotations

import sys
from typing import Awaitable, Callable

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


def _check_exception(exc: pytest.ExceptionInfo) -> None:
    assert isinstance(exc.value, BaseExceptionGroup)
    assert len(exc.value.exceptions) == 1
    assert isinstance(exc.value.exceptions[0], ValueError)


async def main(
    raiser: Callable[[], Awaitable[None]], strict: bool | None = None
) -> None:
    async with trio.open_nursery(strict_exception_groups=strict) as nursery:
        await nursery.start(raiser)


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("raiser", [raise_before, raise_after_started])
async def test_strict_before_started(
    strict: bool, raiser: Callable[[], Awaitable[None]]
) -> None:
    with pytest.raises(BaseExceptionGroup if strict else ValueError) as exc:
        await main(raiser, strict)
    if strict:
        _check_exception(exc)


# it was only when run from `trio.run` that the double wrapping happened
@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("raiser", [raise_before, raise_after_started])
def test_trio_run_strict_before_started(
    strict: bool, raiser: Callable[[], Awaitable[None]]
) -> None:
    with pytest.raises(BaseExceptionGroup if strict else ValueError) as exc:
        trio.run(main, raiser, strict_exception_groups=strict)
    if strict:
        _check_exception(exc)


# TODO: this shouldn't doublewrap, but should it modify the exception/traceback in any way?
def test_trio_run_strict_exceptiongroup_before_started() -> None:
    async def raise_custom_exception_group_before(
        *, task_status: TaskStatus[None]
    ) -> None:
        raise ExceptionGroup("my group", [ValueError()])

    with pytest.raises(BaseExceptionGroup) as exc:
        trio.run(
            main, raise_custom_exception_group_before, strict_exception_groups=True
        )
    _check_exception(exc)
