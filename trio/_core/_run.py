import functools
import itertools
import logging
import os
import random
import select
import sys
import threading
from collections import deque
import collections.abc
from contextlib import contextmanager, closing

from contextvars import copy_context
from math import inf, isnan
from time import perf_counter

from sniffio import current_async_library_cvar

import attr
from async_generator import isasyncgen
from sortedcontainers import SortedDict
from outcome import Error, Value, capture

from . import _public
from ._entry_queue import EntryQueue, TrioToken
from ._exceptions import (TrioInternalError, RunFinishedError, Cancelled)
from ._ki import (
    LOCALS_KEY_KI_PROTECTION_ENABLED, ki_manager, enable_ki_protection
)
from ._multierror import MultiError
from ._traps import (
    Abort,
    wait_task_rescheduled,
    CancelShieldedCheckpoint,
    PermanentlyDetachCoroutineObject,
    WaitTaskRescheduled,
)
from .. import _core
from .._deprecate import deprecated

# At the bottom of this file there's also some "clever" code that generates
# wrapper functions for runner and io manager methods, and adds them to
# __all__. These are all re-exported as part of the 'trio' or 'trio.hazmat'
# namespaces.
__all__ = [
    "Task", "run", "open_nursery", "open_cancel_scope", "CancelScope",
    "checkpoint", "current_task", "current_effective_deadline",
    "checkpoint_if_cancelled", "TASK_STATUS_IGNORED"
]

GLOBAL_RUN_CONTEXT = threading.local()

if os.name == "nt":
    from ._io_windows import WindowsIOManager as TheIOManager
elif hasattr(select, "epoll"):
    from ._io_epoll import EpollIOManager as TheIOManager
elif hasattr(select, "kqueue"):
    from ._io_kqueue import KqueueIOManager as TheIOManager
else:  # pragma: no cover
    raise NotImplementedError("unsupported platform")

# When running under Hypothesis, we want examples to be reproducible and
# shrinkable.  pytest-trio's Hypothesis integration monkeypatches this
# variable to True, and registers the Random instance _r for Hypothesis
# to manage for each test case, which together should make Trio's task
# scheduling loop deterministic.  We have a test for that, of course.
_ALLOW_DETERMINISTIC_SCHEDULING = False
_r = random.Random()

# Used to log exceptions in instruments
INSTRUMENT_LOGGER = logging.getLogger("trio.abc.Instrument")


# On 3.7+, Context.run() is implemented in C and doesn't show up in
# tracebacks. On 3.6 and earlier, we use the contextvars backport, which is
# currently implemented in Python and adds 1 frame to tracebacks. So this
# function is a super-overkill version of "0 if sys.version_info >= (3, 7)
# else 1". But if Context.run ever changes, we'll be ready!
#
# This can all be removed once we drop support for 3.6.
def _count_context_run_tb_frames():
    def function_with_unique_name_xyzzy():
        1 / 0

    ctx = copy_context()
    try:
        ctx.run(function_with_unique_name_xyzzy)
    except ZeroDivisionError as exc:
        tb = exc.__traceback__
        # Skip the frame where we caught it
        tb = tb.tb_next
        count = 0
        while tb.tb_frame.f_code.co_name != "function_with_unique_name_xyzzy":
            tb = tb.tb_next
            count += 1
        return count


CONTEXT_RUN_TB_FRAMES = _count_context_run_tb_frames()


@attr.s(frozen=True)
class SystemClock:
    # Add a large random offset to our clock to ensure that if people
    # accidentally call time.perf_counter() directly or start comparing clocks
    # between different runs, then they'll notice the bug quickly:
    offset = attr.ib(default=attr.Factory(lambda: _r.uniform(10000, 200000)))

    def start_clock(self):
        pass

    # In cPython 3, on every platform except Windows, perf_counter is
    # exactly the same as time.monotonic; and on Windows, it uses
    # QueryPerformanceCounter instead of GetTickCount64.
    def current_time(self):
        return self.offset + perf_counter()

    def deadline_to_sleep_time(self, deadline):
        return deadline - self.current_time()


################################################################
# CancelScope and friends
################################################################


def _convert_deadline(arg):
    result = float(arg)
    if isnan(result):
        raise ValueError("deadlines cannot be NaN")
    return result


@attr.s(cmp=False, repr=False, slots=True)
class CancelScope:
    """A *cancellation scope*: the link between a unit of cancellable
    work and Trio's cancellation system.

    A :class:`CancelScope` becomes associated with some cancellable work
    when it is used as a context manager surrounding that work::

        cancel_scope = trio.CancelScope()
        ...
        with cancel_scope:
            await long_running_operation()

    Inside the ``with`` block, a cancellation of ``cancel_scope`` (via
    a call to its :meth:`cancel` method or via the expiry of its
    :attr:`deadline`) will immediately interrupt the
    ``long_running_operation()`` by raising :exc:`Cancelled` at its
    next :ref:`checkpoint <checkpoints>`.

    The context manager ``__enter__`` returns the :class:`CancelScope`
    object itself, so you can also write ``with trio.CancelScope() as
    cancel_scope:``.

    If a cancel scope becomes cancelled before entering its ``with`` block,
    the :exc:`Cancelled` exception will be raised at the first
    checkpoint inside the ``with`` block. This allows a
    :class:`CancelScope` to be created in one :ref:`task <tasks>` and
    passed to another, so that the first task can later cancel some work
    inside the second.

    Cancel scopes are not reusable or reentrant; that is, each cancel
    scope can be used for at most one ``with`` block.  (You'll get a
    :exc:`RuntimeError` if you violate this rule.)

    The :class:`CancelScope` constructor takes initial values for the
    cancel scope's :attr:`deadline`, :attr:`cleanup_deadline`,
    :attr:`shield`, and :attr:`shield_during_cleanup` attributes;
    these may be freely modified after construction, whether or not
    the scope has been entered yet, and changes take immediate effect.

    """

    # The set of tasks that might possibly be affected by a cancellation
    # of this cancel scope
    _tasks = attr.ib(factory=set, init=False)

    # True if we have entered the cancel scope's 'with' block yet, and
    # shouldn't be allowed to enter it again
    _has_been_entered = attr.ib(default=False, init=False)

    # True if cancel() has been called or the deadline has expired
    cancel_called = attr.ib(default=False, init=False)

    # True if we passed the _cleanup_deadline time before exiting the
    # 'with' block, either via a deadline callback or via cancel()
    # with no grace period
    cleanup_expired = attr.ib(default=False, init=False)

    # True if the 'with' block caught a Cancelled exception
    cancelled_caught = attr.ib(default=False, init=False)

    # If other than +inf, this is the time at which we have registered
    # ourselves in Runner.deadlines to have
    # _registered_deadline_expired() called.
    # This is _deadline until cancel_called is True, then
    # _cleanup_deadline until cleanup_expired is True, then +inf;
    # except that it's always +inf if we have no _tasks.
    _registered_deadline = attr.ib(default=inf, init=False)

    # Constructor arguments:
    _deadline = attr.ib(default=inf, converter=_convert_deadline, kw_only=True)
    _cleanup_deadline = attr.ib(
        default=attr.Factory(lambda self: self._deadline, takes_self=True),
        converter=_convert_deadline,
        kw_only=True
    )
    _shield = attr.ib(
        default=False,
        validator=attr.validators.instance_of(bool),
        kw_only=True
    )
    _shield_during_cleanup = attr.ib(
        default=False,
        validator=attr.validators.instance_of(bool),
        kw_only=True
    )

    @enable_ki_protection
    def __enter__(self):
        task = _core.current_task()
        if self._has_been_entered:
            raise RuntimeError(
                "Each CancelScope may only be used for a single 'with' block"
            )
        self._has_been_entered = True
        now = current_time()
        if now >= self._deadline:
            self.cancel_called = True
        if now >= self._cleanup_deadline:
            self.cleanup_expired = True
        self._add_task(task)
        self._update_registered_deadline()
        return self

    @enable_ki_protection
    def __exit__(self, etype, exc, tb):
        # NB: NurseryManager calls _close() directly rather than __exit__(),
        # so __exit__() must be just _close() plus this logic for adapting
        # the exception-filtering result to the context manager API.

        # Tracebacks show the 'raise' line below out of context, so let's give
        # this variable a name that makes sense out of context.
        remaining_error_after_cancel_scope = self._close(exc)
        if remaining_error_after_cancel_scope is None:
            return True
        elif remaining_error_after_cancel_scope is exc:
            return False
        else:
            # Copied verbatim from MultiErrorCatcher.  Python doesn't
            # allow us to encapsulate this __context__ fixup.
            old_context = remaining_error_after_cancel_scope.__context__
            try:
                raise remaining_error_after_cancel_scope
            finally:
                _, value, _ = sys.exc_info()
                assert value is remaining_error_after_cancel_scope
                value.__context__ = old_context

    def __repr__(self):
        if self._tasks:
            binding = "bound to {} task{}".format(
                len(self._tasks), "s" if len(self._tasks) > 1 else ""
            )
        elif self._has_been_entered:
            binding = "exited"
        else:
            binding = "unbound"

        try:
            now = current_time()
        except RuntimeError:  # must be called from async context
            now = None

        if self.cleanup_expired:
            state = ", cancelled"
        elif self.cancel_called:
            state = ", cancelled pending cleanup"
            if now is not None and self._cleanup_deadline != inf:
                state += ", cleanup deadline is {:.2f} seconds {}".format(
                    abs(self._cleanup_deadline - now),
                    "from now" if self._cleanup_deadline >= now else "ago"
                )
        elif self.deadline != inf and now is not None:
            state = ", deadline is {:.2f} seconds {}".format(
                abs(self.deadline - now),
                "from now" if self.deadline >= now else "ago"
            )
        else:
            state = ""

        return "<trio.CancelScope at {:#x}, {}{}>".format(
            id(self), binding, state
        )

    @enable_ki_protection
    def _update_registered_deadline(self):
        old = self._registered_deadline
        if self.cleanup_expired or not self._tasks:
            # After grace period expires, no more callbacks needed.
            # If no tasks are attached, our cancellation has no impact.
            new = inf
        elif self.cancel_called:
            # cancel() has been called (or deadline expired) but
            # grace period is still ticking -- set up to be called
            # back when the grace period expires
            new = self._cleanup_deadline
        else:
            new = self._deadline

        if old != new:
            self._registered_deadline = new
            runner = GLOBAL_RUN_CONTEXT.runner
            if old != inf:
                del runner.deadlines[old, id(self)]
            if new != inf:
                runner.deadlines[new, id(self)] = self

    @property
    def deadline(self):
        """Read-write, :class:`float`. An absolute time on the current
        run's clock at which this scope will automatically become
        cancelled. You can adjust the deadline by modifying this
        attribute, e.g.::

           # I need a little more time!
           cancel_scope.deadline += 30

        Note that for efficiency, the core run loop only checks for
        expired deadlines every once in a while. This means that in
        certain cases there may be a short delay between when the clock
        says the deadline should have expired, and when checkpoints
        start raising :exc:`~trio.Cancelled`. This is a very obscure
        corner case that you're unlikely to notice, but we document it
        for completeness. (If this *does* cause problems for you, of
        course, then `we want to know!
        <https://github.com/python-trio/trio/issues>`__)

        Changing the deadline will also change the :attr:`cleanup_deadline`
        so as to keep the difference between the two attributes the
        same as it was before. Changing the deadline from infinity
        to some finite value will set the cleanup deadline to that same
        value.

        Defaults to :data:`math.inf`, which means "no deadline", though
        this can be overridden by the ``deadline=`` argument to
        the :class:`~trio.CancelScope` constructor.
        """
        return self._deadline

    @deadline.setter
    def deadline(self, new_deadline):
        old_deadline = self._deadline
        self._deadline = _convert_deadline(new_deadline)
        if old_deadline == inf and self._deadline != inf:
            self._cleanup_deadline = self._deadline
        elif old_deadline != self._deadline:  # avoid inf minus inf creating NaN
            self._cleanup_deadline += self._deadline - old_deadline
        self._update_registered_deadline()

    @property
    def cleanup_deadline(self):
        """Read-write, :class:`float`. An absolute time on the current run's
        clock at which the cancellation of this scope will extend to
        also cover nested scopes that set
        :attr:`shield_during_cleanup` to :data:`True`.

        Normally this is set implicitly by the ``grace_period`` argument
        to :func:`move_on_after` and friends; for example,
        ``move_on_at(DEADLINE, grace_period=5)`` creates a cancel scope
        with ``cleanup_deadline = DEADLINE + 5``.

        You can modify this attribute.  Setting it earlier than the
        :attr:`deadline` is allowed, but will not result in a
        cancellation being delivered before the :attr:`deadline` in
        the absence of an explicit call to :meth:`cancel`. Calls to
        :meth:`cancel` may also implicitly modify the
        :attr:`cleanup_deadline`; see the :meth:`cancel` documentation
        for details.

        The default :attr:`cleanup_deadline` is the specified :attr:`deadline`,
        i.e., no grace period.
        """
        return self._cleanup_deadline

    @cleanup_deadline.setter
    def cleanup_deadline(self, new_deadline):
        new_deadline = _convert_deadline(new_deadline)
        self._cleanup_deadline = new_deadline
        self._update_registered_deadline()

    @property
    def shield(self):
        """Read-write, :class:`bool`, default :data:`False`. So long as
        this is set to :data:`True`, then the code inside this scope
        will not receive :exc:`~trio.Cancelled` exceptions from scopes
        that are outside this scope. They can still receive
        :exc:`~trio.Cancelled` exceptions from (1) this scope, or (2)
        scopes inside this scope. You can modify this attribute::

           with trio.CancelScope() as cancel_scope:
               cancel_scope.shield = True
               # This cannot be interrupted by any means short of
               # killing the process:
               await sleep(10)

               cancel_scope.shield = False
               # Now this can be cancelled normally:
               await sleep(10)

        Defaults to :data:`False`, though this can be overridden by the
        ``shield=`` argument to the :class:`~trio.CancelScope` constructor.
        """
        return self._shield

    @shield.setter
    def shield(self, new_value):
        self._set_shield("_shield", new_value)

    @property
    def shield_during_cleanup(self):
        """Read-write, :class:`bool`, default :data:`False`. Like
        :attr:`shield`, but instead of shielding this scope from outside
        cancellations indefinitely, it only shields until the outside
        cancellation's :attr:`cleanup_deadline` expires. This allows for
        :ref:`blocking cleanup <cleanup-with-grace-period>` whose maximum
        duration is specified externally.

        You can set both :attr:`shield` and
        :attr:`shield_during_cleanup` independently, but
        :attr:`shield` offers strictly more protection, so if
        :attr:`shield` is :data:`True` then the value of
        :attr:`shield_during_cleanup` doesn't matter.
        """
        return self._shield_during_cleanup

    @shield_during_cleanup.setter
    def shield_during_cleanup(self, new_value):
        self._set_shield("_shield_during_cleanup", new_value)

    @enable_ki_protection
    def _set_shield(self, attr_name, new_value):
        if not isinstance(new_value, bool):
            raise TypeError("{} must be a bool".format(attr_name.lstrip("_")))
        setattr(self, attr_name, new_value)
        if not new_value:
            for task in self._tasks:
                task._attempt_delivery_of_any_pending_cancel()

    @enable_ki_protection
    def cancel(self, *, grace_period=0, _as_of=None):
        """Cancels this scope immediately.

        Multiple calls to :meth:`cancel` with the same ``grace_period``
        are idempotent. Calling :meth:`cancel` again with a shorter
        ``grace_period`` may reduce the amount of time available for
        cleanup; the resulting :attr:`cleanup_deadline` is the minimum
        of the cleanup deadlines implied by all calls to :meth:`cancel`.

        Args:
          grace_period (float): If specified, wait this many seconds
              before extending this cancellation to also cover nested
              scopes that set :attr:`shield_during_cleanup` to
              :data:`True`. This is implemented by decreasing
              :attr:`cleanup_deadline` to at most :func:`current_time`
              plus ``grace_period``. If no ``grace_period`` is given,
              perform a full cancellation immediately.

        """
        if self.cleanup_expired:
            return
        self.cancel_called = True
        now = _as_of if _as_of is not None else current_time()
        self._cleanup_deadline = min(
            self._cleanup_deadline, now + grace_period
        )
        self.cleanup_expired = (now >= self._cleanup_deadline)
        self._update_registered_deadline()
        for task in self._tasks:
            task._attempt_delivery_of_any_pending_cancel()

    def _registered_deadline_expired(self, as_of):
        if not self.cancel_called:
            self.cancel(grace_period=inf, _as_of=as_of)
        else:
            assert not self.cleanup_expired
            self.cancel(grace_period=0, _as_of=as_of)

    def _add_task(self, task):
        self._tasks.add(task)
        task._cancel_stack.append(self)

    def _remove_task(self, task):
        self._tasks.remove(task)
        assert task._cancel_stack[-1] is self
        task._cancel_stack.pop()

    # Used by the nursery.start trickiness
    def _tasks_removed_by_adoption(self, tasks):
        self._tasks.difference_update(tasks)
        self._update_registered_deadline()  # might have no tasks left

    # Used by the nursery.start trickiness
    def _tasks_added_by_adoption(self, tasks):
        self._tasks.update(tasks)

    def _exc_filter(self, exc):
        if isinstance(exc, Cancelled):
            self.cancelled_caught = True
            return None
        return exc

    def _close(self, exc):
        scope_task = current_task()
        if (
            exc is not None and self.cancel_called
            and scope_task._pending_cancel_scope() is self
        ):
            exc = MultiError.filter(self._exc_filter, exc)
        self._remove_task(scope_task)
        self._update_registered_deadline()  # might have no tasks left
        return exc


@deprecated("0.10.0", issue=607, instead="trio.CancelScope")
def open_cancel_scope(*, deadline=inf, shield=False):
    """Returns a context manager which creates a new cancellation scope."""
    return CancelScope(deadline=deadline, shield=shield)


################################################################
# Nursery and friends
################################################################


# This code needs to be read alongside the code from Nursery.start to make
# sense.
@attr.s(cmp=False, hash=False, repr=False)
class _TaskStatus:
    _old_nursery = attr.ib()
    _new_nursery = attr.ib()
    _called_started = attr.ib(default=False)
    _value = attr.ib(default=None)

    def __repr__(self):
        return "<Task status object at {:#x}>".format(id(self))

    def started(self, value=None):
        if self._called_started:
            raise RuntimeError(
                "called 'started' twice on the same task status"
            )
        self._called_started = True
        self._value = value

        # If the old nursery is cancelled, then quietly quit now; the child
        # will eventually exit on its own, and we don't want to risk moving
        # children that might have propagating Cancelled exceptions into
        # a place with no cancelled cancel scopes to catch them.
        if _pending_cancel_scope(self._old_nursery._cancel_stack) is not None:
            return

        # Can't be closed, b/c we checked in start() and then _pending_starts
        # should keep it open.
        assert not self._new_nursery._closed

        # otherwise, find all the tasks under the old nursery, and move them
        # under the new nursery instead. This means:
        # - changing parents of direct children
        # - changing cancel stack of all direct+indirect children
        # - changing cancel stack of all direct+indirect children's nurseries
        # - checking for cancellation in all changed cancel stacks
        old_stack = self._old_nursery._cancel_stack
        new_stack = self._new_nursery._cancel_stack
        # LIFO todo stack for depth-first traversal
        todo = list(self._old_nursery._children)
        munged_tasks = []
        while todo:
            task = todo.pop()
            # Direct children need to be reparented
            if task._parent_nursery is self._old_nursery:
                self._old_nursery._children.remove(task)
                task._parent_nursery = self._new_nursery
                self._new_nursery._children.add(task)
            # Everyone needs their cancel scopes fixed up...
            assert task._cancel_stack[:len(old_stack)] == old_stack
            task._cancel_stack[:len(old_stack)] = new_stack
            # ...and their nurseries' cancel scopes fixed up.
            for nursery in task._child_nurseries:
                assert nursery._cancel_stack[:len(old_stack)] == old_stack
                nursery._cancel_stack[:len(old_stack)] = new_stack
                # And then add all the nursery's children to our todo list
                todo.extend(nursery._children)
            # And make a note to check for cancellation later
            munged_tasks.append(task)

        # Tell all the cancel scopes about the change. (There are probably
        # some scopes in common between the two stacks, so some scopes will
        # get the same tasks removed and then immediately re-added. This is
        # fine though.)
        for cancel_scope in old_stack:
            cancel_scope._tasks_removed_by_adoption(munged_tasks)
        for cancel_scope in new_stack:
            cancel_scope._tasks_added_by_adoption(munged_tasks)

        # That should have removed all the children from the old nursery
        assert not self._old_nursery._children

        # After all the delicate surgery is done, check for cancellation in
        # all the tasks that had their cancel scopes munged. This can trigger
        # arbitrary abort() callbacks, so we put it off until our internal
        # data structures are all self-consistent again.
        for task in munged_tasks:
            task._attempt_delivery_of_any_pending_cancel()

        # And finally, poke the old nursery so it notices that all its
        # children have disappeared and can exit.
        self._old_nursery._check_nursery_closed()


class NurseryManager:
    """Nursery context manager.

    Note we explicitly avoid @asynccontextmanager and @async_generator
    since they add a lot of extraneous stack frames to exceptions, as
    well as cause problematic behavior with handling of StopIteration
    and StopAsyncIteration.

    """

    @enable_ki_protection
    async def __aenter__(self):
        self._scope = CancelScope()
        self._scope.__enter__()
        self._nursery = Nursery(current_task(), self._scope)
        return self._nursery

    @enable_ki_protection
    async def __aexit__(self, etype, exc, tb):
        new_exc = await self._nursery._nested_child_finished(exc)
        # Tracebacks show the 'raise' line below out of context, so let's give
        # this variable a name that makes sense out of context.
        combined_error_from_nursery = self._scope._close(new_exc)
        if combined_error_from_nursery is None:
            return True
        elif combined_error_from_nursery is exc:
            return False
        else:
            # Copied verbatim from MultiErrorCatcher.  Python doesn't
            # allow us to encapsulate this __context__ fixup.
            old_context = combined_error_from_nursery.__context__
            try:
                raise combined_error_from_nursery
            finally:
                _, value, _ = sys.exc_info()
                assert value is combined_error_from_nursery
                value.__context__ = old_context

    def __enter__(self):
        raise RuntimeError(
            "use 'async with open_nursery(...)', not 'with open_nursery(...)'"
        )

    def __exit__(self):  # pragma: no cover
        assert False, """Never called, but should be defined"""


def open_nursery():
    """Returns an async context manager which must be used to create a
    new ``Nursery``.

    It does not block on entry; on exit it blocks until all child tasks
    have exited.

    """
    return NurseryManager()


def _is_only_cancelleds(exc):
    return isinstance(exc, _core.Cancelled) or (
        isinstance(exc, _core.MultiError) and all(
            _is_only_cancelleds(subexc) for subexc in exc.exceptions
        )
    )


class Nursery:
    def __init__(self, parent_task, cancel_scope):
        self._parent_task = parent_task
        parent_task._child_nurseries.append(self)
        # the cancel stack that children inherit - we take a snapshot, so it
        # won't be affected by any changes in the parent.
        self._cancel_stack = list(parent_task._cancel_stack)
        # the cancel scope that directly surrounds us; used for cancelling all
        # children.
        self.cancel_scope = cancel_scope
        assert self.cancel_scope is self._cancel_stack[-1]
        self._children = set()
        self._pending_excs = []
        # The "nested child" is how this code refers to the contents of the
        # nursery's 'async with' block, which acts like a child Task in all
        # the ways we can make it.
        self._nested_child_running = True
        self._parent_waiting_in_aexit = False
        self._pending_starts = 0
        self._closed = False

    @property
    def child_tasks(self):
        return frozenset(self._children)

    @property
    def parent_task(self):
        return self._parent_task

    def _add_exc(self, exc):
        self._pending_excs.append(exc)
        if _is_only_cancelleds(exc):
            # A cancellation that propagates out of a task must be
            # associated with some cancel scope in the nursery's cancel
            # stack. If that scope is cancelled, it's cancelled for all
            # tasks in the nursery, and adding our own cancellation on
            # top of that (with a potentially different grace period)
            # just confuses things.
            pass
        else:
            self.cancel_scope.cancel()

    def _check_nursery_closed(self):
        if not any(
            [self._nested_child_running, self._children, self._pending_starts]
        ):
            self._closed = True
            if self._parent_waiting_in_aexit:
                self._parent_waiting_in_aexit = False
                GLOBAL_RUN_CONTEXT.runner.reschedule(self._parent_task)

    def _child_finished(self, task, outcome):
        self._children.remove(task)
        if type(outcome) is Error:
            self._add_exc(outcome.error)
        self._check_nursery_closed()

    async def _nested_child_finished(self, nested_child_exc):
        """Returns MultiError instance if there are pending exceptions."""
        if nested_child_exc is not None:
            self._add_exc(nested_child_exc)
        self._nested_child_running = False
        self._check_nursery_closed()

        if not self._closed:
            # If we get cancelled (or have an exception injected, like
            # KeyboardInterrupt), then save that, but still wait until our
            # children finish.
            def aborted(raise_cancel):
                self._add_exc(capture(raise_cancel).error)
                return Abort.FAILED

            self._parent_waiting_in_aexit = True
            await wait_task_rescheduled(aborted)
        else:
            # Nothing to wait for, so just execute a checkpoint -- but we
            # still need to mix any exception (e.g. from an external
            # cancellation) in with the rest of our exceptions.
            try:
                await checkpoint()
            except BaseException as exc:
                self._add_exc(exc)

        popped = self._parent_task._child_nurseries.pop()
        assert popped is self
        if self._pending_excs:
            return MultiError(self._pending_excs)

    def start_soon(self, async_fn, *args, name=None):
        GLOBAL_RUN_CONTEXT.runner.spawn_impl(async_fn, args, self, name)

    async def start(self, async_fn, *args, name=None):
        if self._closed:
            raise RuntimeError("Nursery is closed to new arrivals")
        try:
            self._pending_starts += 1
            async with open_nursery() as old_nursery:
                task_status = _TaskStatus(old_nursery, self)
                thunk = functools.partial(async_fn, task_status=task_status)
                old_nursery.start_soon(thunk, *args, name=name)
                # Wait for either _TaskStatus.started or an exception to
                # cancel this nursery:
            # If we get here, then the child either got reparented or exited
            # normally. The complicated logic is all in _TaskStatus.started().
            # (Any exceptions propagate directly out of the above.)
            if not task_status._called_started:
                raise RuntimeError(
                    "child exited without calling task_status.started()"
                )
            return task_status._value
        finally:
            self._pending_starts -= 1
            self._check_nursery_closed()

    def __del__(self):
        assert not self._children


################################################################
# Task and friends
################################################################


def _pending_cancel_scope(cancel_stack):
    # Return the outermost of the following two possibilities:
    # - the outermost cancel scope in cleanup state (cancel_called and not
    #   cleanup_expired) that is not outside a shield_during_cleanup
    # - the outermost cancel scope in fully-cancelled state
    #   (cleanup_expired, which implies also cancel_called)
    #   that is not outside any kind of shield

    pending_scope = None
    pending_with_cleanup_expired = None

    for scope in cancel_stack:
        # Check shielding before cancellation state, because shield
        # should not block processing of *this* scope's exception
        if scope._shield:
            # Full shield: nothing outside this scope can affect a task
            # that is currently executing code inside the scope.
            pending_scope = None
            pending_with_cleanup_expired = None

        if scope._shield_during_cleanup:
            # Shield during cleanup: only cancel scopes with cleanup_expired
            # outside this scope can affect a task that's executing code
            # inside it.
            pending_scope = pending_with_cleanup_expired

        if pending_scope is None and scope.cancel_called:
            pending_scope = scope

        if pending_with_cleanup_expired is None and scope.cleanup_expired:
            pending_with_cleanup_expired = scope

    return pending_scope


@attr.s(cmp=False, hash=False, repr=False)
class Task:
    _parent_nursery = attr.ib()
    coro = attr.ib()
    _runner = attr.ib()
    name = attr.ib()
    # PEP 567 contextvars context
    context = attr.ib()
    _counter = attr.ib(init=False, factory=itertools.count().__next__)

    # Invariant:
    # - for unscheduled tasks, _next_send is None
    # - for scheduled tasks, _next_send is an Outcome object,
    #   and custom_sleep_data is None
    # Tasks start out unscheduled.
    _next_send = attr.ib(default=None)
    _abort_func = attr.ib(default=None)
    custom_sleep_data = attr.ib(default=None)

    # For introspection and nursery.start()
    _child_nurseries = attr.ib(default=attr.Factory(list))

    # these are counts of how many cancel/schedule points this task has
    # executed, for assert{_no,}_yields
    # XX maybe these should be exposed as part of a statistics() method?
    _cancel_points = attr.ib(default=0)
    _schedule_points = attr.ib(default=0)

    def __repr__(self):
        return ("<Task {!r} at {:#x}>".format(self.name, id(self)))

    @property
    def parent_nursery(self):
        """The nursery this task is inside (or None if this is the "init"
        task).

        Example use case: drawing a visualization of the task tree in a
        debugger.

        """
        return self._parent_nursery

    @property
    def child_nurseries(self):
        """The nurseries this task contains.

        This is a list, with outer nurseries before inner nurseries.

        """
        return list(self._child_nurseries)

    ################
    # Cancellation
    ################

    _cancel_stack = attr.ib(default=attr.Factory(list), repr=False)

    def _pending_cancel_scope(self):
        return _pending_cancel_scope(self._cancel_stack)

    def _attempt_abort(self, raise_cancel):
        # Either the abort succeeds, in which case we will reschedule the
        # task, or else it fails, in which case it will worry about
        # rescheduling itself (hopefully eventually calling reraise to raise
        # the given exception, but not necessarily).
        success = self._abort_func(raise_cancel)
        if type(success) is not Abort:
            raise TrioInternalError("abort function must return Abort enum")
        # We only attempt to abort once per blocking call, regardless of
        # whether we succeeded or failed.
        self._abort_func = None
        if success is Abort.SUCCEEDED:
            self._runner.reschedule(self, capture(raise_cancel))

    def _attempt_delivery_of_any_pending_cancel(self):
        if self._abort_func is None:
            return
        if self._pending_cancel_scope() is None:
            return

        def raise_cancel():
            raise Cancelled._init()

        self._attempt_abort(raise_cancel)

    def _attempt_delivery_of_pending_ki(self):
        assert self._runner.ki_pending
        if self._abort_func is None:
            return

        def raise_cancel():
            self._runner.ki_pending = False
            raise KeyboardInterrupt

        self._attempt_abort(raise_cancel)


################################################################
# The central Runner object
################################################################


@attr.s(frozen=True)
class _RunStatistics:
    tasks_living = attr.ib()
    tasks_runnable = attr.ib()
    seconds_to_next_deadline = attr.ib()
    io_statistics = attr.ib()
    run_sync_soon_queue_size = attr.ib()


@attr.s(cmp=False, hash=False)
class Runner:
    clock = attr.ib()
    instruments = attr.ib()
    io_manager = attr.ib()

    # Run-local values, see _local.py
    _locals = attr.ib(default=attr.Factory(dict))

    runq = attr.ib(default=attr.Factory(deque))
    tasks = attr.ib(default=attr.Factory(set))

    # {(deadline, id(CancelScope)): CancelScope}
    # only contains scopes with non-infinite deadlines that are currently
    # attached to at least one task
    deadlines = attr.ib(default=attr.Factory(SortedDict))

    init_task = attr.ib(default=None)
    system_nursery = attr.ib(default=None)
    system_context = attr.ib(default=None)
    main_task = attr.ib(default=None)
    main_task_outcome = attr.ib(default=None)

    entry_queue = attr.ib(default=attr.Factory(EntryQueue))
    trio_token = attr.ib(default=None)

    _NO_SEND = object()

    def close(self):
        self.io_manager.close()
        self.entry_queue.close()
        if self.instruments:
            self.instrument("after_run")

    # Methods marked with @_public get converted into functions exported by
    # trio.hazmat:
    @_public
    def current_statistics(self):
        """Returns an object containing run-loop-level debugging information.

        Currently the following fields are defined:

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
          :meth:`trio.hazmat.TrioToken.run_sync_soon`.
        * ``io_statistics`` (object): Some statistics from trio's I/O
          backend. This always has an attribute ``backend`` which is a string
          naming which operating-system-specific I/O backend is in use; the
          other attributes vary between backends.

        """
        if self.deadlines:
            next_deadline, _ = self.deadlines.keys()[0]
            seconds_to_next_deadline = next_deadline - self.current_time()
        else:
            seconds_to_next_deadline = float("inf")
        return _RunStatistics(
            tasks_living=len(self.tasks),
            tasks_runnable=len(self.runq),
            seconds_to_next_deadline=seconds_to_next_deadline,
            io_statistics=self.io_manager.statistics(),
            run_sync_soon_queue_size=self.entry_queue.size(),
        )

    @_public
    def current_time(self):
        """Returns the current time according to trio's internal clock.

        Returns:
            float: The current time.

        Raises:
            RuntimeError: if not inside a call to :func:`trio.run`.

        """
        return self.clock.current_time()

    @_public
    def current_clock(self):
        """Returns the current :class:`~trio.abc.Clock`.

        """
        return self.clock

    @_public
    def current_root_task(self):
        """Returns the current root :class:`Task`.

        This is the task that is the ultimate parent of all other tasks.

        """
        return self.init_task

    ################
    # Core task handling primitives
    ################

    @_public
    def reschedule(self, task, next_send=_NO_SEND):
        """Reschedule the given task with the given
        :class:`outcome.Outcome`.

        See :func:`wait_task_rescheduled` for the gory details.

        There must be exactly one call to :func:`reschedule` for every call to
        :func:`wait_task_rescheduled`. (And when counting, keep in mind that
        returning :data:`Abort.SUCCEEDED` from an abort callback is equivalent
        to calling :func:`reschedule` once.)

        Args:
          task (trio.hazmat.Task): the task to be rescheduled. Must be blocked
            in a call to :func:`wait_task_rescheduled`.
          next_send (outcome.Outcome): the value (or error) to return (or
            raise) from :func:`wait_task_rescheduled`.

        """
        if next_send is self._NO_SEND:
            next_send = Value(None)

        assert task._runner is self
        assert task._next_send is None
        task._next_send = next_send
        task._abort_func = None
        task.custom_sleep_data = None
        self.runq.append(task)
        if self.instruments:
            self.instrument("task_scheduled", task)

    def spawn_impl(self, async_fn, args, nursery, name, *, system_task=False):

        ######
        # Make sure the nursery is in working order
        ######

        # This sorta feels like it should be a method on nursery, except it
        # has to handle nursery=None for init. And it touches the internals of
        # all kinds of objects.
        if nursery is not None and nursery._closed:
            raise RuntimeError("Nursery is closed to new arrivals")
        if nursery is None:
            assert self.init_task is None

        ######
        # Call the function and get the coroutine object, while giving helpful
        # errors for common mistakes.
        ######

        def _return_value_looks_like_wrong_library(value):
            # Returned by legacy @asyncio.coroutine functions, which includes
            # a surprising proportion of asyncio builtins.
            if isinstance(value, collections.abc.Generator):
                return True
            # The protocol for detecting an asyncio Future-like object
            if getattr(value, "_asyncio_future_blocking", None) is not None:
                return True
            # asyncio.Future doesn't have _asyncio_future_blocking until
            # 3.5.3. We don't want to import asyncio, but this janky check
            # should work well enough for our purposes. And it also catches
            # tornado Futures and twisted Deferreds. By the time we're calling
            # this function, we already know something has gone wrong, so a
            # heuristic is pretty safe.
            if value.__class__.__name__ in ("Future", "Deferred"):
                return True
            return False

        try:
            coro = async_fn(*args)
        except TypeError:
            # Give good error for: nursery.start_soon(trio.sleep(1))
            if isinstance(async_fn, collections.abc.Coroutine):
                raise TypeError(
                    "trio was expecting an async function, but instead it got "
                    "a coroutine object {async_fn!r}\n"
                    "\n"
                    "Probably you did something like:\n"
                    "\n"
                    "  trio.run({async_fn.__name__}(...))            # incorrect!\n"
                    "  nursery.start_soon({async_fn.__name__}(...))  # incorrect!\n"
                    "\n"
                    "Instead, you want (notice the parentheses!):\n"
                    "\n"
                    "  trio.run({async_fn.__name__}, ...)            # correct!\n"
                    "  nursery.start_soon({async_fn.__name__}, ...)  # correct!"
                    .format(async_fn=async_fn)
                ) from None

            # Give good error for: nursery.start_soon(future)
            if _return_value_looks_like_wrong_library(async_fn):
                raise TypeError(
                    "trio was expecting an async function, but instead it got "
                    "{!r} – are you trying to use a library written for "
                    "asyncio/twisted/tornado or similar? That won't work "
                    "without some sort of compatibility shim."
                    .format(async_fn)
                ) from None

            raise

        # We can't check iscoroutinefunction(async_fn), because that will fail
        # for things like functools.partial objects wrapping an async
        # function. So we have to just call it and then check whether the
        # return value is a coroutine object.
        if not isinstance(coro, collections.abc.Coroutine):
            # Give good error for: nursery.start_soon(func_returning_future)
            if _return_value_looks_like_wrong_library(coro):
                raise TypeError(
                    "start_soon got unexpected {!r} – are you trying to use a "
                    "library written for asyncio/twisted/tornado or similar? "
                    "That won't work without some sort of compatibility shim."
                    .format(coro)
                )

            if isasyncgen(coro):
                raise TypeError(
                    "start_soon expected an async function but got an async "
                    "generator {!r}".format(coro)
                )

            # Give good error for: nursery.start_soon(some_sync_fn)
            raise TypeError(
                "trio expected an async function, but {!r} appears to be "
                "synchronous".format(
                    getattr(async_fn, "__qualname__", async_fn)
                )
            )

        ######
        # Set up the Task object
        ######

        if name is None:
            name = async_fn
        if isinstance(name, functools.partial):
            name = name.func
        if not isinstance(name, str):
            try:
                name = "{}.{}".format(name.__module__, name.__qualname__)
            except AttributeError:
                name = repr(name)

        if system_task:
            context = self.system_context.copy()
        else:
            context = copy_context()

        task = Task(
            coro=coro,
            parent_nursery=nursery,
            runner=self,
            name=name,
            context=context,
        )
        self.tasks.add(task)
        coro.cr_frame.f_locals.setdefault(
            LOCALS_KEY_KI_PROTECTION_ENABLED, system_task
        )

        if nursery is not None:
            nursery._children.add(task)
            for scope in nursery._cancel_stack:
                scope._add_task(task)

        if self.instruments:
            self.instrument("task_spawned", task)
        # Special case: normally next_send should be an Outcome, but for the
        # very first send we have to send a literal unboxed None.
        self.reschedule(task, None)
        return task

    def task_exited(self, task, outcome):
        while task._cancel_stack:
            task._cancel_stack[-1]._remove_task(task)
        self.tasks.remove(task)
        if task is self.main_task:
            self.main_task_outcome = outcome
            self.system_nursery.cancel_scope.cancel()
            self.system_nursery._child_finished(task, Value(None))
        elif task is self.init_task:
            # If the init task crashed, then something is very wrong and we
            # let the error propagate. (It'll eventually be wrapped in a
            # TrioInternalError.)
            outcome.unwrap()
            # the init task should be the last task to exit. If not, then
            # something is very wrong.
            if self.tasks:  # pragma: no cover
                raise TrioInternalError
        else:
            task._parent_nursery._child_finished(task, outcome)

        if self.instruments:
            self.instrument("task_exited", task)

    ################
    # System tasks and init
    ################

    @_public
    def spawn_system_task(self, async_fn, *args, name=None):
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

        Returns:
          Task: the newly spawned task

        """

        return self.spawn_impl(
            async_fn, args, self.system_nursery, name, system_task=True
        )

    async def init(self, async_fn, args):
        async with open_nursery() as system_nursery:
            self.system_nursery = system_nursery
            try:
                self.main_task = self.spawn_impl(
                    async_fn, args, system_nursery, None
                )
            except BaseException as exc:
                self.main_task_outcome = Error(exc)
                system_nursery.cancel_scope.cancel()
            self.entry_queue.spawn()

    ################
    # Outside context problems
    ################

    @_public
    def current_trio_token(self):
        """Retrieve the :class:`TrioToken` for the current call to
        :func:`trio.run`.

        """
        if self.trio_token is None:
            self.trio_token = TrioToken(self.entry_queue)
        return self.trio_token

    ################
    # KI handling
    ################

    ki_pending = attr.ib(default=False)

    # deliver_ki is broke. Maybe move all the actual logic and state into
    # RunToken, and we'll only have one instance per runner? But then we can't
    # have a public constructor. Eh, but current_run_token() returning a
    # unique object per run feels pretty nice. Maybe let's just go for it. And
    # keep the class public so people can isinstance() it if they want.

    # This gets called from signal context
    def deliver_ki(self):
        self.ki_pending = True
        try:
            self.entry_queue.run_sync_soon(self._deliver_ki_cb)
        except RunFinishedError:
            pass

    def _deliver_ki_cb(self):
        if not self.ki_pending:
            return
        # Can't happen because main_task and run_sync_soon_task are created at
        # the same time -- so even if KI arrives before main_task is created,
        # we won't get here until afterwards.
        assert self.main_task is not None
        if self.main_task_outcome is not None:
            # We're already in the process of exiting -- leave ki_pending set
            # and we'll check it again on our way out of run().
            return
        self.main_task._attempt_delivery_of_pending_ki()

    ################
    # Quiescing
    ################

    waiting_for_idle = attr.ib(default=attr.Factory(SortedDict))

    @_public
    async def wait_all_tasks_blocked(self, cushion=0.0, tiebreaker=0):
        """Block until there are no runnable tasks.

        This is useful in testing code when you want to give other tasks a
        chance to "settle down". The calling task is blocked, and doesn't wake
        up until all other tasks are also blocked for at least ``cushion``
        seconds. (Setting a non-zero ``cushion`` is intended to handle cases
        like two tasks talking to each other over a local socket, where we
        want to ignore the potential brief moment between a send and receive
        when all tasks are blocked.)

        Note that ``cushion`` is measured in *real* time, not the trio clock
        time.

        If there are multiple tasks blocked in :func:`wait_all_tasks_blocked`,
        then the one with the shortest ``cushion`` is the one woken (and
        this task becoming unblocked resets the timers for the remaining
        tasks). If there are multiple tasks that have exactly the same
        ``cushion``, then the one with the lowest ``tiebreaker`` value is
        woken first. And if there are multiple tasks with the same ``cushion``
        and the same ``tiebreaker``, then all are woken.

        You should also consider :class:`trio.testing.Sequencer`, which
        provides a more explicit way to control execution ordering within a
        test, and will often produce more readable tests.

        Example:
          Here's an example of one way to test that trio's locks are fair: we
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
                     child = nursery.start_soon(lock_taker, lock)
                     # child hasn't run yet, we have the lock
                     assert lock.locked()
                     assert lock._owner is trio.current_task()
                     await trio.testing.wait_all_tasks_blocked()
                     # now the child has run and is blocked on lock.acquire(), we
                     # still have the lock
                     assert lock.locked()
                     assert lock._owner is trio.current_task()
                     lock.release()
                     try:
                         # The child has a prior claim, so we can't have it
                         lock.acquire_nowait()
                     except trio.WouldBlock:
                         assert lock._owner is child
                         print("PASS")
                     else:
                         print("FAIL")

        """
        task = current_task()
        key = (cushion, tiebreaker, id(task))
        self.waiting_for_idle[key] = task

        def abort(_):
            del self.waiting_for_idle[key]
            return Abort.SUCCEEDED

        await wait_task_rescheduled(abort)

    ################
    # Instrumentation
    ################

    def instrument(self, method_name, *args):
        if not self.instruments:
            return

        for instrument in list(self.instruments):
            try:
                method = getattr(instrument, method_name)
            except AttributeError:
                continue
            try:
                method(*args)
            except:
                self.instruments.remove(instrument)
                INSTRUMENT_LOGGER.exception(
                    "Exception raised when calling %r on instrument %r. "
                    "Instrument has been disabled.", method_name, instrument
                )

    @_public
    def add_instrument(self, instrument):
        """Start instrumenting the current run loop with the given instrument.

        Args:
          instrument (trio.abc.Instrument): The instrument to activate.

        If ``instrument`` is already active, does nothing.

        """
        if instrument not in self.instruments:
            self.instruments.append(instrument)

    @_public
    def remove_instrument(self, instrument):
        """Stop instrumenting the current run loop with the given instrument.

        Args:
          instrument (trio.abc.Instrument): The instrument to de-activate.

        Raises:
          KeyError: if the instrument is not currently active. This could
              occur either because you never added it, or because you added it
              and then it raised an unhandled exception and was automatically
              deactivated.

        """
        # We're moving 'instruments' to being a set, so raise KeyError like
        # set.remove does.
        try:
            self.instruments.remove(instrument)
        except ValueError as exc:
            raise KeyError(*exc.args)


################################################################
# run
################################################################


def run(
    async_fn,
    *args,
    clock=None,
    instruments=(),
    restrict_keyboard_interrupt_to_checkpoints=False
):
    """Run a trio-flavored async function, and return the result.

    Calling::

       run(async_fn, *args)

    is the equivalent of::

       await async_fn(*args)

    except that :func:`run` can (and must) be called from a synchronous
    context.

    This is trio's main entry point. Almost every other function in trio
    requires that you be inside a call to :func:`run`.

    Args:
      async_fn: An async function.

      args: Positional arguments to be passed to *async_fn*. If you need to
          pass keyword arguments, then use :func:`functools.partial`.

      clock: ``None`` to use the default system-specific monotonic clock;
          otherwise, an object implementing the :class:`trio.abc.Clock`
          interface, like (for example) a :class:`trio.testing.MockClock`
          instance.

      instruments (list of :class:`trio.abc.Instrument` objects): Any
          instrumentation you want to apply to this run. This can also be
          modified during the run; see :ref:`instrumentation`.

      restrict_keyboard_interrupt_to_checkpoints (bool): What happens if the
          user hits control-C while :func:`run` is running? If this argument
          is False (the default), then you get the standard Python behavior: a
          :exc:`KeyboardInterrupt` exception will immediately interrupt
          whatever task is running (or if no task is running, then trio will
          wake up a task to be interrupted). Alternatively, if you set this
          argument to True, then :exc:`KeyboardInterrupt` delivery will be
          delayed: it will be *only* be raised at :ref:`checkpoints
          <checkpoints>`, like a :exc:`Cancelled` exception.

          The default behavior is nice because it means that even if you
          accidentally write an infinite loop that never executes any
          checkpoints, then you can still break out of it using control-C.
          The alternative behavior is nice if you're paranoid about a
          :exc:`KeyboardInterrupt` at just the wrong place leaving your
          program in an inconsistent state, because it means that you only
          have to worry about :exc:`KeyboardInterrupt` at the exact same
          places where you already have to worry about :exc:`Cancelled`.

          This setting has no effect if your program has registered a custom
          SIGINT handler, or if :func:`run` is called from anywhere but the
          main thread (this is a Python limitation), or if you use
          :func:`open_signal_receiver` to catch SIGINT.

    Returns:
      Whatever ``async_fn`` returns.

    Raises:
      TrioInternalError: if an unexpected error is encountered inside trio's
          internal machinery. This is a bug and you should `let us know
          <https://github.com/python-trio/trio/issues>`__.

      Anything else: if ``async_fn`` raises an exception, then :func:`run`
          propagates it.

    """

    __tracebackhide__ = True

    # Do error-checking up front, before we enter the TrioInternalError
    # try/catch
    #
    # It wouldn't be *hard* to support nested calls to run(), but I can't
    # think of a single good reason for it, so let's be conservative for
    # now:
    if hasattr(GLOBAL_RUN_CONTEXT, "runner"):
        raise RuntimeError("Attempted to call run() from inside a run()")

    if clock is None:
        clock = SystemClock()
    instruments = list(instruments)
    io_manager = TheIOManager()
    system_context = copy_context()
    system_context.run(current_async_library_cvar.set, "trio")
    runner = Runner(
        clock=clock,
        instruments=instruments,
        io_manager=io_manager,
        system_context=system_context,
    )
    GLOBAL_RUN_CONTEXT.runner = runner
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True

    # KI handling goes outside the core try/except/finally to avoid a window
    # where KeyboardInterrupt would be allowed and converted into an
    # TrioInternalError:
    try:
        with ki_manager(
            runner.deliver_ki, restrict_keyboard_interrupt_to_checkpoints
        ):
            try:
                with closing(runner):
                    # The main reason this is split off into its own function
                    # is just to get rid of this extra indentation.
                    run_impl(runner, async_fn, args)
            except TrioInternalError:
                raise
            except BaseException as exc:
                raise TrioInternalError(
                    "internal error in trio - please file a bug!"
                ) from exc
            finally:
                GLOBAL_RUN_CONTEXT.__dict__.clear()
            # Inlined copy of runner.main_task_outcome.unwrap() to avoid
            # cluttering every single trio traceback with an extra frame.
            if type(runner.main_task_outcome) is Value:
                return runner.main_task_outcome.value
            else:
                raise runner.main_task_outcome.error
    finally:
        # To guarantee that we never swallow a KeyboardInterrupt, we have to
        # check for pending ones once more after leaving the context manager:
        if runner.ki_pending:
            # Implicitly chains with any exception from outcome.unwrap():
            raise KeyboardInterrupt


# 24 hours is arbitrary, but it avoids issues like people setting timeouts of
# 10**20 and then getting integer overflows in the underlying system calls.
_MAX_TIMEOUT = 24 * 60 * 60


def run_impl(runner, async_fn, args):
    __tracebackhide__ = True

    if runner.instruments:
        runner.instrument("before_run")
    runner.clock.start_clock()
    runner.init_task = runner.spawn_impl(
        runner.init,
        (async_fn, args),
        None,
        "<init>",
        system_task=True,
    )

    # You know how people talk about "event loops"? This 'while' loop right
    # here is our event loop:
    while runner.tasks:
        if runner.runq:
            timeout = 0
        elif runner.deadlines:
            deadline, _ = runner.deadlines.keys()[0]
            timeout = runner.clock.deadline_to_sleep_time(deadline)
        else:
            timeout = _MAX_TIMEOUT
        timeout = min(max(0, timeout), _MAX_TIMEOUT)

        idle_primed = False
        if runner.waiting_for_idle:
            cushion, tiebreaker, _ = runner.waiting_for_idle.keys()[0]
            if cushion < timeout:
                timeout = cushion
                idle_primed = True

        if runner.instruments:
            runner.instrument("before_io_wait", timeout)

        runner.io_manager.handle_io(timeout)

        if runner.instruments:
            runner.instrument("after_io_wait", timeout)

        # Process cancellations due to deadline expiry
        now = runner.clock.current_time()
        while runner.deadlines:
            (deadline, _), cancel_scope = runner.deadlines.peekitem(0)
            if deadline <= now:
                # This removes the given scope from runner.deadlines,
                # or reinserts it with a later deadline if there's a
                # grace period involved.
                cancel_scope._registered_deadline_expired(now)
                idle_primed = False
            else:
                break

        if not runner.runq and idle_primed:
            while runner.waiting_for_idle:
                key, task = runner.waiting_for_idle.peekitem(0)
                if key[:2] == (cushion, tiebreaker):
                    del runner.waiting_for_idle[key]
                    runner.reschedule(task)
                else:
                    break

        # Process all runnable tasks, but only the ones that are already
        # runnable now. Anything that becomes runnable during this cycle needs
        # to wait until the next pass. This avoids various starvation issues
        # by ensuring that there's never an unbounded delay between successive
        # checks for I/O.
        #
        # Also, we randomize the order of each batch to avoid assumptions
        # about scheduling order sneaking in. In the long run, I suspect we'll
        # either (a) use strict FIFO ordering and document that for
        # predictability/determinism, or (b) implement a more sophisticated
        # scheduler (e.g. some variant of fair queueing), for better behavior
        # under load. For now, this is the worst of both worlds - but it keeps
        # our options open. (If we do decide to go all in on deterministic
        # scheduling, then there are other things that will probably need to
        # change too, like the deadlines tie-breaker and the non-deterministic
        # ordering of task._notify_queues.)
        batch = list(runner.runq)
        if _ALLOW_DETERMINISTIC_SCHEDULING:
            # We're running under Hypothesis, and pytest-trio has patched this
            # in to make the scheduler deterministic and avoid flaky tests.
            # It's not worth the (small) performance cost in normal operation,
            # since we'll shuffle the list and _r is only seeded for tests.
            batch.sort(key=lambda t: t._counter)
        runner.runq.clear()
        _r.shuffle(batch)
        while batch:
            task = batch.pop()
            GLOBAL_RUN_CONTEXT.task = task

            if runner.instruments:
                runner.instrument("before_task_step", task)

            next_send = task._next_send
            task._next_send = None
            final_outcome = None
            try:
                # We used to unwrap the Outcome object here and send/throw its
                # contents in directly, but it turns out that .throw() is
                # buggy, at least on CPython 3.6 and earlier:
                #   https://bugs.python.org/issue29587
                #   https://bugs.python.org/issue29590
                # So now we send in the Outcome object and unwrap it on the
                # other side.
                msg = task.context.run(task.coro.send, next_send)
            except StopIteration as stop_iteration:
                final_outcome = Value(stop_iteration.value)
            except BaseException as task_exc:
                # Store for later, removing uninteresting top frames: 1 frame
                # we always remove, because it's this function catching it,
                # and then in addition we remove however many more Context.run
                # adds.
                tb = task_exc.__traceback__.tb_next
                for _ in range(CONTEXT_RUN_TB_FRAMES):
                    tb = tb.tb_next
                final_outcome = Error(task_exc.with_traceback(tb))

            if final_outcome is not None:
                # We can't call this directly inside the except: blocks above,
                # because then the exceptions end up attaching themselves to
                # other exceptions as __context__ in unwanted ways.
                runner.task_exited(task, final_outcome)
            else:
                task._schedule_points += 1
                if msg is CancelShieldedCheckpoint:
                    runner.reschedule(task)
                elif type(msg) is WaitTaskRescheduled:
                    task._cancel_points += 1
                    task._abort_func = msg.abort_func
                    # KI is "outside" all cancel scopes, so check for it
                    # before checking for regular cancellation:
                    if runner.ki_pending and task is runner.main_task:
                        task._attempt_delivery_of_pending_ki()
                    task._attempt_delivery_of_any_pending_cancel()
                elif type(msg) is PermanentlyDetachCoroutineObject:
                    # Pretend the task just exited with the given outcome
                    runner.task_exited(task, msg.final_outcome)
                else:
                    exc = TypeError(
                        "trio.run received unrecognized yield message {!r}. "
                        "Are you trying to use a library written for some "
                        "other framework like asyncio? That won't work "
                        "without some kind of compatibility shim.".format(msg)
                    )
                    # How can we resume this task? It's blocked in code we
                    # don't control, waiting for some message that we know
                    # nothing about. We *could* try using coro.throw(...) to
                    # blast an exception in and hope that it propagates out,
                    # but (a) that's complicated because we aren't set up to
                    # resume a task via .throw(), and (b) even if we did,
                    # there's no guarantee that the foreign code will respond
                    # the way we're hoping. So instead we abandon this task
                    # and propagate the exception into the task's spawner.
                    runner.task_exited(task, Error(exc))

            if runner.instruments:
                runner.instrument("after_task_step", task)
            del GLOBAL_RUN_CONTEXT.task


################################################################
# Other public API functions
################################################################


class _TaskStatusIgnored:
    def __repr__(self):
        return "TASK_STATUS_IGNORED"

    def started(self, value=None):
        pass


TASK_STATUS_IGNORED = _TaskStatusIgnored()


def current_task():
    """Return the :class:`Task` object representing the current task.

    Returns:
      Task: the :class:`Task` that called :func:`current_task`.

    """

    try:
        return GLOBAL_RUN_CONTEXT.task
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


def current_effective_deadline():
    """Returns the current effective deadline for the current task.

    This function examines all the cancellation scopes that are currently in
    effect (taking into account shielding), and returns the deadline that will
    expire first.

    One example of where this might be is useful is if your code is trying to
    decide whether to begin an expensive operation like an RPC call, but wants
    to skip it if it knows that it can't possibly complete in the available
    time. Another example would be if you're using a protocol like gRPC that
    `propagates timeout information to the remote peer
    <http://www.grpc.io/docs/guides/concepts.html#deadlines>`__; this function
    gives a way to fetch that information so you can send it along.

    If this is called in a context where a cancellation is currently active
    (i.e., a blocking call will immediately raise :exc:`Cancelled`), then
    returned deadline is ``-inf``. If it is called in a context where no
    scopes have a deadline set, it returns ``inf``.

    Returns:
        float: the effective deadline, as an absolute time.

    """
    task = current_task()
    deadline = inf
    cleanup_deadline = inf

    for scope in task._cancel_stack:
        if scope._shield:
            deadline = cleanup_deadline = inf
        if scope._shield_during_cleanup:
            deadline = cleanup_deadline

        if scope.cleanup_expired:
            cleanup_deadline = -inf
        else:
            cleanup_deadline = min(
                cleanup_deadline, scope._cleanup_deadline
            )

        if scope.cancel_called:
            deadline = -inf
        else:
            deadline = min(deadline, scope._deadline)

    return deadline


async def checkpoint():
    """A pure :ref:`checkpoint <checkpoints>`.

    This checks for cancellation and allows other tasks to be scheduled,
    without otherwise blocking.

    Note that the scheduler has the option of ignoring this and continuing to
    run the current task if it decides this is appropriate (e.g. for increased
    efficiency).

    Equivalent to ``await trio.sleep(0)`` (which is implemented by calling
    :func:`checkpoint`.)

    """
    with CancelScope(deadline=-inf):
        await _core.wait_task_rescheduled(lambda _: _core.Abort.SUCCEEDED)


async def checkpoint_if_cancelled():
    """Issue a :ref:`checkpoint <checkpoints>` if the calling context has been
    cancelled.

    Equivalent to (but potentially more efficient than)::

        if trio.current_effective_deadline() == -inf:
            await trio.hazmat.checkpoint()

    This is either a no-op, or else it allow other tasks to be scheduled and
    then raises :exc:`trio.Cancelled`.

    Typically used together with :func:`cancel_shielded_checkpoint`.

    """
    task = current_task()
    if (
        task._pending_cancel_scope() is not None or
        (task is task._runner.main_task and task._runner.ki_pending)
    ):
        await _core.checkpoint()
        assert False  # pragma: no cover
    task._cancel_points += 1


_WRAPPER_TEMPLATE = """
def wrapper(*args, **kwargs):
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        meth = GLOBAL_RUN_CONTEXT.{}.{}
    except AttributeError:
        raise RuntimeError("must be called from async context") from None
    return meth(*args, **kwargs)
"""


def _generate_method_wrappers(cls, path_to_instance):
    for methname, fn in cls.__dict__.items():
        if callable(fn) and getattr(fn, "_public", False):
            # Create a wrapper function that looks up this method in the
            # current thread-local context version of this object, and calls
            # it. exec() is a bit ugly but the resulting code is faster and
            # simpler than doing some loop over getattr.
            ns = {
                "GLOBAL_RUN_CONTEXT":
                    GLOBAL_RUN_CONTEXT,
                "LOCALS_KEY_KI_PROTECTION_ENABLED":
                    LOCALS_KEY_KI_PROTECTION_ENABLED
            }
            exec(_WRAPPER_TEMPLATE.format(path_to_instance, methname), ns)
            wrapper = ns["wrapper"]
            # 'fn' is the *unbound* version of the method, but our exported
            # function has the same API as the *bound* version of the
            # method. So create a dummy bound method object:
            from types import MethodType
            bound_fn = MethodType(fn, object())
            # Then set exported function's metadata to match it:
            from functools import update_wrapper
            update_wrapper(wrapper, bound_fn)
            # And finally export it:
            globals()[methname] = wrapper
            __all__.append(methname)


_generate_method_wrappers(Runner, "runner")
_generate_method_wrappers(TheIOManager, "runner.io_manager")
