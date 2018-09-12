from contextlib import contextmanager

from .. import _core

__all__ = ["assert_checkpoints", "assert_no_checkpoints"]


@contextmanager
def _assert_yields_or_not(expected):
    __tracebackhide__ = True
    task = _core.current_task()
    orig_cancel = task._cancel_points
    orig_schedule = task._schedule_points
    try:
        yield
    finally:
        if (
            expected and (
                task._cancel_points == orig_cancel
                or task._schedule_points == orig_schedule
            )
        ):
            raise AssertionError("assert_checkpoints block did not yield!")
        elif (
            not expected and (
                task._cancel_points != orig_cancel
                or task._schedule_points != orig_schedule
            )
        ):
            raise AssertionError("assert_no_yields block yielded!")


def assert_checkpoints():
    """Use as a context manager to check that the code inside the ``with``
    block executes at least one :ref:`checkpoint <checkpoints>`.

    Raises:
      AssertionError: if no checkpoint was executed.

    Example:
      Check that :func:`trio.sleep` is a checkpoint, even if it doesn't
      block::

         with trio.testing.assert_checkpoints():
             await trio.sleep(0)

    """
    __tracebackhide__ = True
    return _assert_yields_or_not(True)


def assert_no_checkpoints():
    """Use as a context manager to check that the code inside the ``with``
    block does not execute any :ref:`check points <checkpoints>`.

    Raises:
      AssertionError: if a checkpoint was executed.

    Example:
      Synchronous code never contains any checkpoints, but we can double-check
      that::

         queue = trio.Queue(10)
         with trio.testing.assert_no_checkpoints():
             queue.put_nowait(None)

    """
    __tracebackhide__ = True
    return _assert_yields_or_not(False)
