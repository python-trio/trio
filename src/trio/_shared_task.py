from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Generic, TypeVar, cast

import attr
import outcome

from trio._core._ki import disable_ki_protection, enable_ki_protection
from trio._core._run import CancelScope, spawn_system_task
from trio._sync import Event

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from typing_extensions import ParamSpec, TypeVarTuple, Unpack

    PS = ParamSpec("PS")
    PosArgT = TypeVarTuple("PosArgT")

RetT = TypeVar("RetT")


__all__ = ["SharedTaskRegistry"]


# Here's some cleverness to normalize out functools.partial usage, important
# b/c otherwise there's no way to pass kwargs without having to specify a key=
# manually.
#
# XX should we also do signature cleverness to normalize stuff like
#   def f(x): ...
# and treat these the same:
#   (f, (1,), {})
#   (f, (), {"x": 1})
# ? This is less important b/c we can document that if you want magic key
# generation then you should be careful to make your matching calls obviously
# matching.
def _unpack_call(
    fn: Callable[PS, RetT],
    args: PS.args,
    kwargs: PS.kwargs | dict[str, object],
) -> tuple[Callable[PS, RetT], PS.args, PS.kwargs | dict[str, object]]:
    if isinstance(fn, functools.partial):
        inner_fn, inner_args, inner_kwargs = _unpack_call(fn.func, fn.args, {})
        fn = inner_fn
        args = (*inner_args, *args)
        kwargs = {**inner_kwargs, **kwargs}
    return fn, args, kwargs


def call_to_hashable_key(
    fn: Callable[[Unpack[PosArgT]], RetT],
    args: tuple[Unpack[PosArgT]],
) -> tuple[
    Callable[[Unpack[PosArgT]], RetT],
    tuple[Unpack[PosArgT]],
    tuple[tuple[str, object], ...],
]:
    fn, args, kwargs = _unpack_call(fn, args, {})
    return (fn, args, tuple(sorted(kwargs.items())))


class BaseSharedTask:
    __slots__ = ()


@attr.s
class SharedTask(BaseSharedTask, Generic["Unpack[PosArgT]", RetT]):
    registry: SharedTaskRegistry = attr.ib()
    key: tuple[
        Callable[[Unpack[PosArgT]], Awaitable[RetT]],
        tuple[Unpack[PosArgT]],
        tuple[tuple[str, object], ...],
    ] = attr.ib()
    cancel_scope: CancelScope | None = attr.ib(default=None)
    # Needed to work around a race condition, where we realize we want to
    # cancel the child before it's even created the cancel scope
    cancelled_early: bool = attr.ib(default=False)
    # Reference count
    waiter_count: int = attr.ib(default=0)
    # Reporting back
    finished: Event = attr.ib(default=attr.Factory(Event))
    result: outcome.Value[RetT] | outcome.Error = attr.ib(default=None)

    # This runs in system task context, so it has KI protection enabled and
    # any exceptions will crash the whole program.
    async def run(
        self,
        async_fn: Callable[[Unpack[PosArgT]], Awaitable[RetT]],
        args: tuple[Unpack[PosArgT]],
    ) -> None:
        @disable_ki_protection
        async def ki_unprotected_runner() -> RetT:
            return await async_fn(*args)

        async def cancellable_runner() -> RetT:
            with CancelScope() as cancel_scope:
                self.cancel_scope = cancel_scope
                if self.cancelled_early:
                    self.cancel_scope.cancel()
                return await ki_unprotected_runner()
            raise RuntimeError("Should be unreachable.")

        self.result = await outcome.acapture(cancellable_runner)
        self.finished.set()
        if self.registry._tasks.get(self.key) is self:
            del self.registry._tasks[self.key]


@attr.s(slots=True, frozen=True, hash=False, cmp=False, repr=False)
class SharedTaskRegistry:  # type: ignore[misc]
    _tasks: dict[  # type: ignore[misc]
        tuple[
            Callable[..., Awaitable[object]],
            tuple[object, ...],
            tuple[tuple[str, object], ...],
        ],
        BaseSharedTask,
    ] = attr.ib(default=attr.Factory(dict))

    @enable_ki_protection
    async def run(
        self,
        async_fn: Callable[[Unpack[PosArgT]], Awaitable[RetT]],
        *args: Unpack[PosArgT],
        key: (
            tuple[
                Callable[[Unpack[PosArgT]], Awaitable[RetT]],
                tuple[Unpack[PosArgT]],
                tuple[tuple[str, object], ...],
            ]
            | None
        ) = None,
    ) -> RetT:
        if key is None:
            key = call_to_hashable_key(async_fn, args)

        if key not in self._tasks:
            shared_task = SharedTask["Unpack[PosArgT]", RetT](self, key)
            self._tasks[key] = shared_task
            spawn_system_task(shared_task.run, async_fn, args)

        shared_task = cast("SharedTask[Unpack[PosArgT], RetT]", self._tasks[key])
        shared_task.waiter_count += 1

        try:
            await shared_task.finished.wait()
        except:
            # Cancelled, or some bug
            shared_task.waiter_count -= 1
            if shared_task.waiter_count == 0:
                # Make sure any incoming calls to run() start a new task
                del self._tasks[key]

                # Cancel the child, while working around the race condition
                if shared_task.cancel_scope is None:
                    shared_task.cancelled_early = True
                else:
                    shared_task.cancel_scope.cancel()

                with CancelScope(shield=True):
                    await shared_task.finished.wait()
                    # Some possibilities:
                    # - they raised Cancelled. The cancellation we injected is
                    #   absorbed internally, though, so this can only happen
                    #   if a cancellation came from outside. The only way a
                    #   system task can see this is if the whole system is
                    #   going down, so it's OK to re-raise that -- any scope
                    #   that includes a system task includes all the code in
                    #   trio, including us.
                    # - they raise some other error: we should propagate
                    # - they return nothing (most common, b/c cancelled was
                    #   raised and then
                    assert shared_task.cancel_scope is not None
                    if not shared_task.cancel_scope.cancelled_caught:
                        return shared_task.result.unwrap()
                    else:
                        shared_task.result.unwrap()
            raise

        return shared_task.result.unwrap()
