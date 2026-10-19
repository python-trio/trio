import pickle
import re
import subprocess
import sys
import textwrap
from math import inf

import pytest

import trio
from trio import Cancelled
from trio.lowlevel import current_task
from trio.testing import wait_all_tasks_blocked

from .test_ki import ki_self
from .tutil import slow

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup


def test_Cancelled_init() -> None:
    with pytest.raises(TypeError, match=r"^trio.Cancelled has no public constructor$"):
        raise Cancelled

    with pytest.raises(TypeError, match=r"^trio.Cancelled has no public constructor$"):
        Cancelled(source="explicit")

    # private constructor should not raise
    Cancelled._create(source="explicit")


async def test_Cancelled_str() -> None:
    cancelled = Cancelled._create(source="explicit")
    assert str(cancelled) == "cancelled due to explicit"
    # note: repr(current_task()) is often fairly verbose
    assert re.fullmatch(
        r"cancelled due to deadline from task "
        r"<Task 'trio._core._tests.test_cancelled.test_Cancelled_str' at 0x\w*>",
        str(
            Cancelled._create(
                source="deadline",
                source_task=repr(current_task()),
            )
        ),
    )

    assert re.fullmatch(
        rf"cancelled due to nursery with reason 'pigs flying' from task {current_task()!r}",
        str(
            Cancelled._create(
                source="nursery",
                source_task=repr(current_task()),
                reason="pigs flying",
            )
        ),
    )


def test_Cancelled_subclass() -> None:
    with pytest.raises(TypeError):
        type("Subclass", (Cancelled,), {})


# https://github.com/python-trio/trio/issues/3248
def test_Cancelled_pickle() -> None:
    cancelled = Cancelled._create(source="KeyboardInterrupt")
    pickled_cancelled = pickle.loads(pickle.dumps(cancelled))
    assert isinstance(pickled_cancelled, Cancelled)
    assert cancelled.source == pickled_cancelled.source
    assert cancelled.source_task == pickled_cancelled.source_task
    assert cancelled.reason == pickled_cancelled.reason


async def test_cancel_reason() -> None:
    with trio.CancelScope() as cs:
        cs.cancel(reason="hello")
        with pytest.raises(
            Cancelled,
            match=rf"^cancelled due to explicit with reason 'hello' from task {current_task()!r}$",
        ) as excinfo:
            await trio.lowlevel.checkpoint()
    assert excinfo.value.source == "explicit"
    assert excinfo.value.reason == "hello"
    assert excinfo.value.source_task == repr(current_task())

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


match_str = r"^cancelled due to nursery with reason 'child task raised exception ValueError\(\)' from task {0!r}$"


async def cancelled_task(
    fail_task: trio.lowlevel.Task, task_status: trio.TaskStatus
) -> None:
    task_status.started()
    with pytest.raises(Cancelled, match=match_str.format(fail_task)):
        await trio.sleep_forever()
    raise TypeError


# failing_task raises before cancelled_task is started
async def test_cancel_reason_nursery() -> None:
    async def failing_task(task_status: trio.TaskStatus[trio.lowlevel.Task]) -> None:
        task_status.started(current_task())
        raise ValueError

    with pytest.RaisesGroup(ValueError, TypeError):
        async with trio.open_nursery() as nursery:
            fail_task = await nursery.start(failing_task)
            with pytest.raises(Cancelled, match=match_str.format(fail_task)):
                await wait_all_tasks_blocked()
            await nursery.start(cancelled_task, fail_task)


# wait until both tasks are running before failing_task raises
async def test_cancel_reason_nursery2() -> None:
    async def failing_task(task_status: trio.TaskStatus[trio.lowlevel.Task]) -> None:
        task_status.started(current_task())
        await wait_all_tasks_blocked()
        raise ValueError

    with pytest.RaisesGroup(ValueError, TypeError):
        async with trio.open_nursery() as nursery:
            fail_task = await nursery.start(failing_task)
            await nursery.start(cancelled_task, fail_task)


# failing_task raises before calling task_status.started()
async def test_cancel_reason_nursery3() -> None:
    async def failing_task(task_status: trio.TaskStatus[None]) -> None:
        raise ValueError

    parent_task = current_task()

    async def cancelled_task() -> None:
        # We don't have a way of distinguishing that the nursery code block failed
        # because it failed to `start()` a task.
        with pytest.raises(
            Cancelled,
            match=re.escape(
                rf"cancelled due to nursery with reason 'Code block inside nursery contextmanager raised exception ValueError()' from task {parent_task!r}"
            ),
        ):
            await trio.sleep_forever()

    with pytest.RaisesGroup(ValueError):
        async with trio.open_nursery() as nursery:
            nursery.start_soon(cancelled_task)
            await wait_all_tasks_blocked()
            await nursery.start(failing_task)


@pytest.mark.parametrize("from_child", [False, True])
@pytest.mark.parametrize("grouped", [False, True])
@pytest.mark.parametrize(
    "repr_error", [ValueError, RecursionError, KeyboardInterrupt, SystemExit]
)
async def test_nursery_exception_repr_failure(
    from_child: bool,
    grouped: bool,
    repr_error: type[BaseException],
) -> None:
    class UnprintableError(Exception):
        def __repr__(self) -> str:
            raise repr_error

    original = UnprintableError()
    error: Exception = original
    if grouped:
        for _ in range(20):
            error = ExceptionGroup("nested", [error])

    reasons: list[str | None] = []
    sources: list[str] = []
    finished: list[bool] = []

    async def sibling() -> None:
        try:
            await trio.sleep_forever()
        except Cancelled as exc:
            reasons.append(exc.reason)
            sources.append(exc.source)
            raise
        finally:
            finished.append(True)

    async def failing_task() -> None:
        raise error

    with pytest.raises(ExceptionGroup) as excinfo:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(sibling)
            await wait_all_tasks_blocked()
            if from_child:
                nursery.start_soon(failing_task)
            else:
                raise error

    propagated: BaseException = excinfo.value
    while isinstance(propagated, ExceptionGroup):
        assert len(propagated.exceptions) == 1
        propagated = propagated.exceptions[0]
    assert propagated is original
    assert finished == [True]
    assert sources == ["nursery"]
    prefix = "child task" if from_child else "Code block inside nursery contextmanager"
    assert reasons == [f"{prefix} raised exception <exception repr() failed>"]
    # The nursery has finished unwinding; cancellation must not leak into its parent.
    await trio.lowlevel.checkpoint()


@slow
def test_nursery_exception_repr_recursion() -> None:
    # A real recursion overflow disables coverage tracing on PyPy. Isolate it so
    # coverage can still measure the remaining tests in the parent process.
    code = textwrap.dedent(
        """
        import sys
        import trio

        if sys.version_info < (3, 11):
            from exceptiongroup import ExceptionGroup

        class RecursiveError(Exception):
            def __repr__(self):
                return repr(self)

        original = RecursiveError()

        async def failing_task():
            raise original

        async def main():
            try:
                async with trio.open_nursery() as nursery:
                    nursery.start_soon(failing_task)
            except ExceptionGroup as exc:
                assert len(exc.exceptions) == 1
                assert exc.exceptions[0] is original
            else:
                raise AssertionError("original exception was lost")

        trio.run(main)
        """,
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


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

    with pytest.RaisesGroup(ValueError):
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

    with pytest.RaisesGroup(KeyboardInterrupt):
        async with trio.open_nursery() as nursery:
            nursery.start_soon(sleeper, "s1")
            nursery.start_soon(sleeper, "s2")
            nursery.start_soon(trio.lowlevel.enable_ki_protection(raiser), "r1")
            # __aexit__ blocks, and then receives the KI
