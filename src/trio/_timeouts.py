from __future__ import annotations

import math
import sys
from typing import TYPE_CHECKING, NoReturn

import trio

if TYPE_CHECKING:
    from types import TracebackType


def move_on_at(deadline: float, *, shield: bool = False) -> trio.CancelScope:
    """Use as a context manager to create a cancel scope with the given
    absolute deadline.

    Args:
      deadline (float): The deadline.
      shield (bool): Initial value for the `~trio.CancelScope.shield` attribute
          of the newly created cancel scope.

    Raises:
      ValueError: if deadline is NaN.

    """
    # CancelScope validates that deadline isn't math.nan
    return trio.CancelScope(deadline=deadline, shield=shield)


def move_on_after(
    seconds: float,
    *,
    shield: bool = False,
) -> trio.CancelScope:
    """Use as a context manager to create a cancel scope whose deadline is
    set to now + *seconds*.

    The deadline of the cancel scope is calculated upon entering.

    Args:
      seconds (float): The timeout.
      shield (bool): Initial value for the `~trio.CancelScope.shield` attribute
          of the newly created cancel scope.

    Raises:
      ValueError: if ``seconds`` is less than zero or NaN.

    """
    # duplicate validation logic to have the correct parameter name
    if seconds < 0:
        raise ValueError("`seconds` must be non-negative")
    if math.isnan(seconds):
        raise ValueError("`seconds` must not be NaN")
    return trio.CancelScope(
        shield=shield,
        relative_deadline=seconds,
    )


async def sleep_forever() -> NoReturn:
    """Pause execution of the current task forever (or until cancelled).

    Equivalent to calling ``await sleep(math.inf)``, except that if manually
    rescheduled this will raise a `RuntimeError`.

    Raises:
      RuntimeError: if rescheduled

    """
    await trio.lowlevel.wait_task_rescheduled(lambda _: trio.lowlevel.Abort.SUCCEEDED)
    raise RuntimeError("Should never have been rescheduled!")


async def sleep_until(deadline: float) -> None:
    """Pause execution of the current task until the given time.

    The difference between :func:`sleep` and :func:`sleep_until` is that the
    former takes a relative time and the latter takes an absolute time
    according to Trio's internal clock (as returned by :func:`current_time`).

    Args:
        deadline (float): The time at which we should wake up again. May be in
            the past, in which case this function executes a checkpoint but
            does not block.

    Raises:
      ValueError: if deadline is NaN.

    """
    with move_on_at(deadline):
        await sleep_forever()


async def sleep(seconds: float) -> None:
    """Pause execution of the current task for the given number of seconds.

    Args:
        seconds (float): The number of seconds to sleep. May be zero to
            insert a checkpoint without actually blocking.

    Raises:
        ValueError: if *seconds* is negative or NaN.

    """
    if seconds < 0:
        raise ValueError("`seconds` must be non-negative")
    if seconds == 0:
        await trio.lowlevel.checkpoint()
    else:
        await sleep_until(trio.current_time() + seconds)


class TooSlowError(Exception):
    """Raised by :func:`fail_after` and :func:`fail_at` if the timeout
    expires.

    """


class _FailScope:
    """The object returned by :func:`fail_at` and :func:`fail_after`.

    Wraps the underlying `~trio.CancelScope` so that its attributes (such
    as ``deadline`` and ``relative_deadline``) can be inspected and
    modified before the scope is entered, which a plain context manager
    does not allow. Entering it enters the wrapped scope and returns the
    scope itself; exiting raises `TooSlowError` if the scope caught a
    cancellation, exactly as the previous generator-based implementation
    did. All other attribute access is passed through to the wrapped
    scope.
    """

    def __init__(self, scope: trio.CancelScope) -> None:
        object.__setattr__(self, "_scope", scope)

    def __enter__(self) -> trio.CancelScope:
        return self._scope.__enter__()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        suppressed = self._scope.__exit__(exc_type, exc_value, traceback)
        if self._scope.cancelled_caught and (exc_type is None or suppressed):
            raise TooSlowError
        return suppressed

    def __getattr__(self, name: str) -> object:
        if name == "_scope":
            raise AttributeError(name)
        return getattr(self._scope, name)

    def __setattr__(self, name: str, value: object) -> None:
        if name == "_scope":
            object.__setattr__(self, name, value)
        else:
            setattr(self._scope, name, value)

    def __repr__(self) -> str:
        return f"<fail scope wrapping {self._scope!r}>"


def fail_at(
    deadline: float,
    *,
    shield: bool = False,
) -> _FailScope:
    """Creates a cancel scope with the given deadline, and raises an error if it
    is actually cancelled.

    This function and :func:`move_on_at` are similar in that both create a
    cancel scope with a given absolute deadline, and if the deadline expires
    then both will cause :exc:`Cancelled` to be raised within the scope. The
    difference is that when the :exc:`Cancelled` exception reaches
    :func:`move_on_at`, it's caught and discarded. When it reaches
    :func:`fail_at`, then it's caught and :exc:`TooSlowError` is raised in its
    place.

    Args:
      deadline (float): The deadline.
      shield (bool): Initial value for the `~trio.CancelScope.shield` attribute
          of the newly created cancel scope.

    Raises:
      TooSlowError: if a :exc:`Cancelled` exception is raised in this scope
        and caught by the context manager.
      ValueError: if deadline is NaN.

    """
    return _FailScope(move_on_at(deadline, shield=shield))


def fail_after(
    seconds: float,
    *,
    shield: bool = False,
) -> _FailScope:
    """Creates a cancel scope with the given timeout, and raises an error if
    it is actually cancelled.

    This function and :func:`move_on_after` are similar in that both create a
    cancel scope with a given timeout, and if the timeout expires then both
    will cause :exc:`Cancelled` to be raised within the scope. The difference
    is that when the :exc:`Cancelled` exception reaches :func:`move_on_after`,
    it's caught and discarded. When it reaches :func:`fail_after`, then it's
    caught and :exc:`TooSlowError` is raised in its place.

    The deadline of the cancel scope is calculated upon entering.

    Args:
      seconds (float): The timeout.
      shield (bool): Initial value for the `~trio.CancelScope.shield` attribute
          of the newly created cancel scope.

    Raises:
      TooSlowError: if a :exc:`Cancelled` exception is raised in this scope
        and caught by the context manager.
      ValueError: if *seconds* is less than zero or NaN.

    """
    return _FailScope(move_on_after(seconds, shield=shield))


# Users don't need to know that fail_at & fail_after wraps move_on_at and move_on_after
# and there is no functional difference. So we replace the return value when generating
# documentation.
if "sphinx.ext.autodoc" in sys.modules:
    import inspect

    for c in (fail_at, fail_after):
        c.__signature__ = inspect.Signature.from_callable(c).replace(
            return_annotation=trio.CancelScope
        )  # type: ignore[union-attr]
