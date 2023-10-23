# ***********************************************************
# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******
# *************************************************************
from __future__ import annotations

import contextvars
from collections.abc import Awaitable, Callable
from typing import Any

from outcome import Outcome

from .._abc import Clock
from ._entry_queue import TrioToken
from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED
from ._run import _NO_SEND, GLOBAL_RUN_CONTEXT, RunStatistics, Task


def current_statistics() -> RunStatistics:
    """Returns ``RunStatistics``, which contains run-loop-level debugging information.

    Currently, the following fields are defined:

    * ``tasks_living`` (int): The number of tasks that have been spawned
      and not yet exited.
    * ``tasks_runnable`` (int): The number of tasks that are currently
      queued on the run queue (as opposed to blocked waiting for something
      to happen).
    * ``seconds_to_next_deadline`` (float): The time until the next
      pending cancel scope deadline. May be negative if the deadline has
      expired but we haven't yet processed cancellations. May be
      :data:`~math.inf` if there are no pending deadlines.
    * ``run_sync_soon_queue_size`` (int): The number of
      unprocessed callbacks queued via
      :meth:`trio.lowlevel.TrioToken.run_sync_soon`.
    * ``io_statistics`` (object): Some statistics from Trio's I/O
      backend. This always has an attribute ``backend`` which is a string
      naming which operating-system-specific I/O backend is in use; the
      other attributes vary between backends.

    """
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.current_statistics()
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


def current_time() -> float:
    """Returns the current time according to Trio's internal clock.

    Returns:
        float: The current time.

    Raises:
        RuntimeError: if not inside a call to :func:`trio.run`.

    """
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.current_time()
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


def current_clock() -> Clock:
    """Returns the current :class:`~trio.abc.Clock`."""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.current_clock()
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


def current_root_task() -> Task | None:
    """Returns the current root :class:`Task`.

    This is the task that is the ultimate parent of all other tasks.

    """
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.current_root_task()
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


def reschedule(task: Task, next_send: Outcome[Any] = _NO_SEND) -> None:
    """Reschedule the given task with the given
    :class:`outcome.Outcome`.

    See :func:`wait_task_rescheduled` for the gory details.

    There must be exactly one call to :func:`reschedule` for every call to
    :func:`wait_task_rescheduled`. (And when counting, keep in mind that
    returning :data:`Abort.SUCCEEDED` from an abort callback is equivalent
    to calling :func:`reschedule` once.)

    Args:
      task (trio.lowlevel.Task): the task to be rescheduled. Must be blocked
          in a call to :func:`wait_task_rescheduled`.
      next_send (outcome.Outcome): the value (or error) to return (or
          raise) from :func:`wait_task_rescheduled`.

    """
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.reschedule(task, next_send)
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


def spawn_system_task(
    async_fn: Callable[..., Awaitable[object]],
    *args: object,
    name: object = None,
    context: (contextvars.Context | None) = None,
) -> Task:
    """Spawn a "system" task.

    System tasks have a few differences from regular tasks:

    * They don't need an explicit nursery; instead they go into the
      internal "system nursery".

    * If a system task raises an exception, then it's converted into a
      :exc:`~trio.TrioInternalError` and *all* tasks are cancelled. If you
      write a system task, you should be careful to make sure it doesn't
      crash.

    * System tasks are automatically cancelled when the main task exits.

    * By default, system tasks have :exc:`KeyboardInterrupt` protection
      *enabled*. If you want your task to be interruptible by control-C,
      then you need to use :func:`disable_ki_protection` explicitly (and
      come up with some plan for what to do with a
      :exc:`KeyboardInterrupt`, given that system tasks aren't allowed to
      raise exceptions).

    * System tasks do not inherit context variables from their creator.

    Towards the end of a call to :meth:`trio.run`, after the main
    task and all system tasks have exited, the system nursery
    becomes closed. At this point, new calls to
    :func:`spawn_system_task` will raise ``RuntimeError("Nursery
    is closed to new arrivals")`` instead of creating a system
    task. It's possible to encounter this state either in
    a ``finally`` block in an async generator, or in a callback
    passed to :meth:`TrioToken.run_sync_soon` at the right moment.

    Args:
      async_fn: An async callable.
      args: Positional arguments for ``async_fn``. If you want to pass
          keyword arguments, use :func:`functools.partial`.
      name: The name for this task. Only used for debugging/introspection
          (e.g. ``repr(task_obj)``). If this isn't a string,
          :func:`spawn_system_task` will try to make it one. A common use
          case is if you're wrapping a function before spawning a new
          task, you might pass the original function as the ``name=`` to
          make debugging easier.
      context: An optional ``contextvars.Context`` object with context variables
          to use for this task. You would normally get a copy of the current
          context with ``context = contextvars.copy_context()`` and then you would
          pass that ``context`` object here.

    Returns:
      Task: the newly spawned task

    """
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.spawn_system_task(
            async_fn, *args, name=name, context=context
        )
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


def current_trio_token() -> TrioToken:
    """Retrieve the :class:`TrioToken` for the current call to
    :func:`trio.run`.

    """
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.current_trio_token()
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


async def wait_all_tasks_blocked(cushion: float = 0.0) -> None:
    """Block until there are no runnable tasks.

    This is useful in testing code when you want to give other tasks a
    chance to "settle down". The calling task is blocked, and doesn't wake
    up until all other tasks are also blocked for at least ``cushion``
    seconds. (Setting a non-zero ``cushion`` is intended to handle cases
    like two tasks talking to each other over a local socket, where we
    want to ignore the potential brief moment between a send and receive
    when all tasks are blocked.)

    Note that ``cushion`` is measured in *real* time, not the Trio clock
    time.

    If there are multiple tasks blocked in :func:`wait_all_tasks_blocked`,
    then the one with the shortest ``cushion`` is the one woken (and
    this task becoming unblocked resets the timers for the remaining
    tasks). If there are multiple tasks that have exactly the same
    ``cushion``, then all are woken.

    You should also consider :class:`trio.testing.Sequencer`, which
    provides a more explicit way to control execution ordering within a
    test, and will often produce more readable tests.

    Example:
      Here's an example of one way to test that Trio's locks are fair: we
      take the lock in the parent, start a child, wait for the child to be
      blocked waiting for the lock (!), and then check that we can't
      release and immediately re-acquire the lock::

         async def lock_taker(lock):
             await lock.acquire()
             lock.release()

         async def test_lock_fairness():
             lock = trio.Lock()
             await lock.acquire()
             async with trio.open_nursery() as nursery:
                 nursery.start_soon(lock_taker, lock)
                 # child hasn't run yet, we have the lock
                 assert lock.locked()
                 assert lock._owner is trio.lowlevel.current_task()
                 await trio.testing.wait_all_tasks_blocked()
                 # now the child has run and is blocked on lock.acquire(), we
                 # still have the lock
                 assert lock.locked()
                 assert lock._owner is trio.lowlevel.current_task()
                 lock.release()
                 try:
                     # The child has a prior claim, so we can't have it
                     lock.acquire_nowait()
                 except trio.WouldBlock:
                     assert lock._owner is not trio.lowlevel.current_task()
                     print("PASS")
                 else:
                     print("FAIL")

    """
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.wait_all_tasks_blocked(cushion)
    except AttributeError:
        raise RuntimeError("must be called from async context") from None
