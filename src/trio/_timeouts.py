from __future__ import annotations

import math
import warnings
from contextlib import contextmanager
from typing import TYPE_CHECKING

import trio

from ._util import final

if TYPE_CHECKING:
    from collections.abc import Generator
    from types import TracebackType


@final
class _RelativeCancelScope:
    """Makes it possible to specify relative deadlines at initialization, that does
    not start counting until the cm is entered.
    Upon entering it returns a CancelScope, so unless initialization and entering
    are separate, this class will be transparent to end users.
    """

    def __init__(
        self,
        relative_deadline: float,
        *,
        shield: bool = False,
        timeout_from_enter: bool = False,
    ):
        self.relative_deadline = relative_deadline
        self.shield = shield
        self._timeout_from_enter = timeout_from_enter

        self._fail: bool = False
        self._creation_time = trio.current_time()
        self._scope: trio.CancelScope | None = None

    def __enter__(self) -> trio.CancelScope:
        if (
            abs(self._creation_time - trio.current_time()) > 0.01
            and not self._timeout_from_enter
        ):
            # not using warn_deprecated because the message template is a weird fit
            # TODO: mention versions in the message?
            warnings.warn(
                DeprecationWarning(
                    "`move_on_after` and `fail_after` will change behaviour to "
                    "start the deadline relative to entering the cm, instead of "
                    "at creation time. To silence this warning and opt into the "
                    "new behaviour, pass `timeout_from_enter=True`. "
                    "To keep old behaviour, use `move_on_at(trio.current_time() + x)` "
                    "(or `fail_at`), where `x` is the previous timeout length. "
                    "See https://github.com/python-trio/trio/issues/2512",
                ),
                stacklevel=2,
            )

        if self._timeout_from_enter:
            start_time = trio.current_time()
        else:
            start_time = self._creation_time

        self._scope = trio.CancelScope(
            deadline=start_time + self.relative_deadline,
            shield=self.shield,
        )
        self._scope.__enter__()
        return self._scope

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if self._scope is None:  # pragma: no cover
            raise RuntimeError("__exit__ called before __enter__")
        res = self._scope.__exit__(exc_type, exc_value, traceback)
        if self._fail and self._scope.cancelled_caught:
            raise TooSlowError
        return res


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
    if math.isnan(deadline):
        raise ValueError("deadline must not be NaN")
    return trio.CancelScope(deadline=deadline, shield=shield)


def move_on_after(
    seconds: float,
    *,
    shield: bool = False,
    timeout_from_enter: bool = False,
) -> _RelativeCancelScope:
    """Use as a context manager to create a cancel scope whose deadline is
    set to now + *seconds*.

    The deadline of the cancel scope was previously calculated at creation time,
    not upon entering the context manager. This is still the default, but deprecated.
    If you pass ``timeout_from_enter=True`` it will instead be calculated relative
    to entering the cm, and silence the :class:`DeprecationWarning`.

    If you're entering the cancel scope at initialization time, which is the most common
    use case, you can treat this function as returning a :class:`CancelScope`.

    Args:
      seconds (float): The timeout.
      shield (bool): Initial value for the `~trio.CancelScope.shield` attribute
          of the newly created cancel scope.

    Raises:
      ValueError: if timeout is less than zero or NaN.

    """
    if seconds < 0:
        raise ValueError("timeout must be non-negative")
    if math.isnan(seconds):
        raise ValueError("timeout must not be NaN")
    return _RelativeCancelScope(
        shield=shield,
        relative_deadline=seconds,
        timeout_from_enter=timeout_from_enter,
    )


async def sleep_forever() -> None:
    """Pause execution of the current task forever (or until cancelled).

    Equivalent to calling ``await sleep(math.inf)``.

    """
    await trio.lowlevel.wait_task_rescheduled(lambda _: trio.lowlevel.Abort.SUCCEEDED)


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
        raise ValueError("duration must be non-negative")
    if seconds == 0:
        await trio.lowlevel.checkpoint()
    else:
        await sleep_until(trio.current_time() + seconds)


class TooSlowError(Exception):
    """Raised by :func:`fail_after` and :func:`fail_at` if the timeout
    expires.

    """


@contextmanager
def fail_at(
    deadline: float,
    *,
    shield: bool = False,
) -> Generator[trio.CancelScope, None, None]:
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
    with move_on_at(deadline, shield=shield) as scope:
        yield scope
    if scope.cancelled_caught:
        raise TooSlowError


def fail_after(
    seconds: float,
    *,
    shield: bool = False,
    timeout_from_enter: bool = False,
) -> _RelativeCancelScope:
    """Creates a cancel scope with the given timeout, and raises an error if
    it is actually cancelled.

    This function and :func:`move_on_after` are similar in that both create a
    cancel scope with a given timeout, and if the timeout expires then both
    will cause :exc:`Cancelled` to be raised within the scope. The difference
    is that when the :exc:`Cancelled` exception reaches :func:`move_on_after`,
    it's caught and discarded. When it reaches :func:`fail_after`, then it's
    caught and :exc:`TooSlowError` is raised in its place.

    The deadline of the cancel scope was previously calculated at creation time,
    not upon entering the context manager. This is still the default, but deprecated.
    If you pass ``timeout_from_enter=True`` it will instead be calculated relative
    to entering the cm, and silence the :class:`DeprecationWarning`.

    Args:
      seconds (float): The timeout.
      shield (bool): Initial value for the `~trio.CancelScope.shield` attribute
          of the newly created cancel scope.

    Raises:
      TooSlowError: if a :exc:`Cancelled` exception is raised in this scope
        and caught by the context manager.
      ValueError: if *seconds* is less than zero or NaN.

    """
    rcs = move_on_after(seconds, shield=shield, timeout_from_enter=timeout_from_enter)
    rcs._fail = True
    return rcs
