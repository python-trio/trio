from contextlib import contextmanager
import enum
import attr

from .. import _core
from ._traps import Abort

__all__ = ["move_on_at"]

CancelState = enum.Enum("CancelState", "IDLE PENDING DONE")
# IDLE -> hasn't fired, might in the future
# PENDING -> fired, but no exception has been raised yet
# DONE -> either this entry has been delivered, or some lower entry on th
#         stack has become pending

@attr.s(slots=True)
class CancelStackEntry:
    deadline = attr.ib()
    state = attr.ib(default=CancelState.IDLE)
    pending_exc = attr.ib(default=None)
    raised = attr.ib(default=False)

# The cancel stack always has a single entry at the bottom with
# deadline=None representing the cancel() method, and then zero or more
# entries on top of that.
@attr.s(slots=True)
class CancelStack:
    # We assume that there will only be a small number of items on the cancel
    # stack, like 2-4, so simple linear searches make sense. If this turns out
    # to be a problem then some more sophisticated data structure will be
    # called for...
    entries = attr.ib(
        default=attr.Factory(
            lambda: [CancelStackEntry(deadline=None)]))

    def next_deadline(self):
        return min((e.deadline for e in self.entries[1:]
                    if e.state is CancelState.IDLE),
                   default=float("inf"))

    def _pending(self):
        for i in range(len(self.entries)):
            if self.entries[i].state is CancelState.PENDING:
                return i
        return None

    def push_deadline(self, task, deadline):
        deadline = float(deadline)
        stack_entry = CancelStackEntry(deadline=deadline)
        if self._pending() is not None:
            stack_entry.state = CancelState.DONE
        self.entries.append(stack_entry)
        return CancelStatus(stack_entry=stack_entry, task=task)

    def pop_deadline(self, cancel_status):
        assert self.entries[-1] is cancel_status._stack_entry
        self.entries.pop()

    def _get_exception_and_mark_done(self, pending):
        # the given stack entry must be PENDING
        # marks it as delivered, marks all following as DONE, and returns the
        # exception
        stack_entry = self.entries[pending]
        assert stack_entry.state is CancelState.PENDING
        stack_entry.raised = True
        stack_entry.state = CancelState.DONE
        exc = stack_entry.pending_exc
        exc._stack_entry = stack_entry
        # Avoid reference loop
        stack_entry.pending_exc = None
        for i in range(pending + 1, len(self.entries)):
            self.entries[i].state = CancelState.DONE
        return exc

    def _attempt_deliver_cancel_to_blocked_task(self, task, i):
        if task._abort_func is None:
            return
        success = task._abort_func()
        if type(success) is not Abort:
            raise TypeError("abort_func must return Abort enum")
        if success is Abort.SUCCEEDED:
            exc = self._get_exception_and_mark_done(i)
            _core.reschedule(task, _core.Error(exc))

    def _fire_entry(self, task, i, exc):
        assert self.entries[i].state is CancelState.IDLE
        self.entries[i].state = CancelState.PENDING
        self.entries[i].pending_exc = exc
        self._attempt_deliver_cancel_to_blocked_task(task, i)

    def fire_expired_timeouts(self, task, now, exc):
        for i, stack_entry in enumerate(self.entries):
            if i == 0:
                continue
            if (stack_entry.state is CancelState.IDLE
                  and stack_entry.deadline <= now):
                self._fire_entry(task, i, exc)
                break

    def fire_task_cancel(self, task, exc):
        if self.entries[0].state is CancelState.IDLE:
            self._fire_entry(task, 0, exc)
        else:
            # XX Not sure if this pickiness is useful, but easier to start
            # strict and maybe relax it later...
            raise RuntimeError("task was already canceled")

    def deliver_any_pending_cancel_to_blocked_task(self, task):
        pending = self._pending()
        if pending is not None:
            self._attempt_deliver_cancel_to_blocked_task(task, pending)

    def raise_any_pending_cancel(self):
        pending = self._pending()
        if pending is not None:
            raise self._get_exception_and_mark_done(pending)

# This is the opaque object we return from move_on_at(), that lets the user
# check the status and adjust the deadline. It's actually created by
# push_deadline.
@attr.s(slots=True)
class CancelStatus:
    _stack_entry = attr.ib()
    _task = attr.ib()

    @property
    def raised(self):
        return self._stack_entry.raised

    @property
    def deadline(self):
        return self._stack_entry.deadline

    @deadline.setter
    def deadline(self, new_deadline):
        with self._task._might_adjust_deadline():
            self._stack_entry.deadline = new_deadline

@contextmanager
def move_on_at(deadline):
    task = _core.current_task()
    status = task._push_deadline(deadline)
    try:
        yield status
    except _core.Cancelled as exc:
        if exc._stack_entry is status._stack_entry:
            pass
        else:
            raise
    finally:
        task._pop_deadline(status)
