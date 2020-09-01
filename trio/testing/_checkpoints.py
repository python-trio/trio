from contextlib import contextmanager

from .. import _core


@contextmanager
def assert_yields_or_not(expect_cancel_point: bool, expect_schedule_point: bool, msg: str=None):
    __tracebackhide__ = True
    task = _core.current_task()
    orig_cancel = task._cancel_points
    orig_schedule = task._schedule_points
    try:
        yield
        if expect_cancel_point and task._cancel_points == orig_cancel:
            raise AssertionError(msg or "block did not have a cancel point")
        if expect_schedule_point and task._schedule_points == orig_schedule:
            raise AssertionError(msg or "block did not have a schedule point")
    finally:
        if not expect_cancel_point and task._cancel_points != orig_cancel:
            raise AssertionError(msg or "block had a cancel point")
        if not expect_schedule_point and task._schedule_points != orig_schedule:
            raise AssertionError(msg or "block had a schedule point")

def assert_checkpoints():
    """Use as a context manager to check that the code inside the ``with``
    block either exits with an exception or executes at least one
    :ref:`checkpoint <checkpoints>`.

    Raises:
      AssertionError: if no checkpoint was executed.

    Example:
      Check that :func:`trio.sleep` is a checkpoint, even if it doesn't
      block::

         with trio.testing.assert_checkpoints():
             await trio.sleep(0)

    """
    __tracebackhide__ = True
    return assert_yields_or_not(True, True, "assert_checkpoints block did not yield!")


def assert_no_checkpoints():
    """Use as a context manager to check that the code inside the ``with``
    block does not execute any :ref:`checkpoints <checkpoints>`.

    Raises:
      AssertionError: if a checkpoint was executed.

    Example:
      Synchronous code never contains any checkpoints, but we can double-check
      that::

         send_channel, receive_channel = trio.open_memory_channel(10)
         with trio.testing.assert_no_checkpoints():
             send_channel.send_nowait(None)

    """
    __tracebackhide__ = True
    return assert_yields_or_not(False, False, "assert_no_checkpoints block yielded!")
