import abc
import inspect
import enum
from collections import deque
import threading
import queue as stdlib_queue
from time import monotonic
import os
from contextlib import contextmanager, closing

import attr
from sortedcontainers import SortedDict

from .. import _core
from ._exceptions import (
    TaskCrashedError, InternalError, RunFinishedError,
    Cancelled, TaskCancelled, TimeoutCancelled,
)
from ._result import Result, Error, Value
from ._traps import (
    yield_briefly, yield_briefly_no_cancel, Cancel, yield_indefinitely,
)
from ._keyboard_interrupt import (
    LOCALS_KEY_KEYBOARD_INTERRUPT_SAFE, keyboard_interrupt_manager,
)
from ._cancel import CancelStack
from . import _public, _hazmat

# At the bottom of this file there's also some "clever" code that generates
# wrapper functions for runner and io manager methods, and adds them to
# __all__. These are all re-exported as part of the 'trio' or 'trio.hazmat'
# namespaces.
__all__ = ["Clock", "Profiler", "Task", "run",
           "current_task", "current_deadline", "cancellation_point"]

GLOBAL_RUN_CONTEXT = threading.local()


if os.name == "nt":
    from ._io_windows import WindowsIOManager as TheIOManager
else:
    try:
        from ._io_unix import EpollIOManager as TheIOManager
    except ImportError:
        try:
            from ._io_unix import KqueueIOManager as TheIOManager
        except ImportError:
            raise NotImplementedError("unsupported platform")


class Clock(abc.ABC):
    @abc.abstractmethod
    def current_time(self):
        pass

    @abc.abstractmethod
    def deadline_to_sleep_time(self, deadline):
        pass

class SystemClock(Clock):
    def current_time(self):
        return monotonic()

    def deadline_to_sleep_time(self, deadline):
        return deadline - monotonic()


class Profiler(abc.ABC):
    @abc.abstractmethod
    def before_task_step(self, task):
        pass

    @abc.abstractmethod
    def after_task_step(self, task):
        pass

    def close(self):
        pass


# I started out with a DAEMON type as well, and the rules that:
#
# - When all tasks of type X-or-higher have exited, then we cancel all tasks
#   of type (X-1)
# - Tasks of type X can only spawn tasks of type Y where X > Y
# - After a crash we cancel all tasks of type REGULAR (or maybe it should be:
#   after a crash of type X, we cancel all tasks of type X-or-greater?)
#
# ...but this was all getting rather complicated, and I'm not even sure that
# daemon tasks are a good idea. (If you have a robust supervisor system, then
# they seem superfluous?) So I dropped daemon tasks for now; we can add them
# back later if they're really compelling. Now the rules are:
#
# - When all REGULAR tasks have exited, we cancel all SYSTEM tasks.
# - If a REGULAR task crashes, we cancel all REGULAR tasks (once).
# - If a SYSTEM task crashes we exit immediately with InternalError.
#
# Also, the call_soon task can spawn REGULAR tasks, but it checks for crashing
# and immediately cancels them (so they'll get an error at their first
# cancellation point and can figure out what to do from there; for
# await_in_main_thread this should be fine, the exception will propagate back
# to the original thread).
TaskType = enum.Enum("TaskType", "SYSTEM REGULAR")

@attr.s(slots=True, cmp=False, hash=False)
class Task:
    _type = attr.ib()
    coro = attr.ib()
    _runner = attr.ib(repr=False)
    _notify_queues = attr.ib(convert=set, repr=False)
    _task_result = attr.ib(default=None, repr=False)
    # tasks start out unscheduled, and unscheduled tasks have None here
    _next_send = attr.ib(default=None, repr=False)
    _cancel_func = attr.ib(default=None, repr=False)

    def add_notify_queue(self, queue):
        if queue in self._notify_queues:
            raise ValueError("can't add same notify queue twice")
        if self._task_result is not None:
            queue.put_nowait(self)
        else:
            self._notify_queues.add(queue)

    def remove_notify_queue(self, queue):
        if queue not in self._notify_queues:
            raise ValueError("queue not found")
        self._notify_queues.remove(queue)

    ################################################################
    # Cancellation

    _cancel_stack = attr.ib(default=attr.Factory(CancelStack), repr=False)

    def _next_deadline(self):
        return self._cancel_stack.next_deadline()

    @contextmanager
    def _might_adjust_deadline(self):
        old_deadline = self._next_deadline()
        try:
            yield
        finally:
            new_deadline = self._next_deadline()
            if old_deadline != new_deadline:
                if old_deadline != float("inf"):
                    del self._runner.deadlines[old_deadline, id(self)]
                if new_deadline != float("inf"):
                    self._runner.deadlines[new_deadline, id(self)] = self

    def _push_deadline(self, deadline):
        with self._might_adjust_deadline():
            return self._cancel_stack.push_deadline(self, deadline)

    def _pop_deadline(self, cancel_status):
        with self._might_adjust_deadline():
            self._cancel_stack.pop_deadline(cancel_status)

    def _fire_timeouts_at(self, now, exc):
        with self._might_adjust_deadline():
            self._cancel_stack.fire_timeouts(self, now, exc)

    def _deliver_any_pending_cancel_to_blocked_task(self):
        with self._might_adjust_deadline():
            self._cancel_stack.deliver_any_pending_cancel_to_blocked_task(self)

    def _raise_any_pending_cancel(self):
        with self._might_adjust_deadline():
            self._cancel_stack.raise_any_pending_cancel()

    def cancel_nowait(self, exc=None):
        if exc is None:
            exc = TaskCancelled()
        with self._might_adjust_deadline():
            self._cancel_stack.fire_task_cancel(self, exc)

    async def cancel(self, exc=None):
        self.cancel_nowait(exc=exc)
        return await self.join()

    def join_nowait(self):
        if self._task_result is None:
            raise WouldBlock
        else:
            return self._task_result

    async def join(self):
        if self._task_result is None:
            q = _core.Queue()
            self.add_notify_queue(q)
            try:
                await q.get()
            finally:
                self.remove_notify_queue(q)
        assert self._task_result is not None
        return self._task_result

def _call_user_fn(fn, *args):
    locals()[LOCALS_KEY_KEYBOARD_INTERRUPT_SAFE] = True
    return fn(*args)

# Container for the stuff that needs to be accessible for what would be
# synchronous traps in curio.
@attr.s(slots=True)
class Runner:
    clock = attr.ib()
    profilers = attr.ib()
    io_manager = attr.ib()

    runq = attr.ib(default=attr.Factory(deque))
    tasks = attr.ib(default=attr.Factory(set))
    regular_task_count = attr.ib(default=0)

    # {(deadline, id(task)): task}
    deadlines = attr.ib(default=attr.Factory(SortedDict))

    initial_task = attr.ib(default=None)
    final_result = attr.ib(default=None)
    crashing = attr.ib(default=False)

    def close(self):
        for profiler in self.profilers:
            profiler.close()
        self.io_manager.close()

    def crash(self, message, exc):
        # XX ergonomics: maybe KeyboardInterrupt should be preserved instead
        # of being wrapped?
        wrapper = TaskCrashedError(message)
        wrapper.__cause__ = exc
        self.final_result = Result.combine(self.final_result, Error(wrapper))
        if not self.crashing:
            self.crashing = True
            for task in self.tasks:
                if task._type is TaskType.REGULAR:
                    task.cancel_nowait()

    def task_finished(self, task, result):
        self.tasks.remove(task)

        if task._type is TaskType.REGULAR:
            self.regular_task_count -= 1
            if not self.regular_task_count:
                # The last REGULAR task just exited, so we're done; cancel
                # everything.
                for other_task in self.tasks:
                    other_task.cancel_nowait()

        if task is self.initial_task:
            self.final_result = Result.combine(self.final_result, result)
            # Avoid pinning the Task object in memory:
            self.initial_task = None
        elif type(result) is Error and not task._notify_queues:
            if task._type is TaskType.REGULAR:
                self.crash("unwatched task raised exception", result.error)
            else:
                # Propagate system task crashes out, to eventually raise an
                # InternalError.
                assert task._type is TaskType.SYSTEM
                result.unwrap()

        for result_queue in task._notify_queues:
            try:
                result_queue.put_nowait(task)
            except BaseException as exc:
                self.crash("error notifying task watcher of task exit", exc)

    # Methods marked with @_public get converted into functions exported by
    # trio.hazmat:
    @_public
    def current_time(self):
        return self.clock.current_time()

    @_public
    def current_profilers(self):
        return self.profilers

    @_public
    @_hazmat
    def reschedule(self, task, next_send=Value(None)):
        assert task._runner is self
        assert task._next_send is None
        task._next_send = next_send
        task._cancel_func = None
        self.runq.append(task)

    def spawn_impl(self, fn, args, *, type=TaskType.REGULAR, notify_queues=[]):
        if not inspect.iscoroutinefunction(fn):
            raise TypeError("spawn expected an async function")
        coro = fn(*args)
        task = Task(
            type=type, coro=coro, runner=self, notify_queues=notify_queues)
        self.tasks.add(task)
        if type is TaskType.REGULAR:
            self.regular_task_count += 1
            coro.cr_frame.f_locals[LOCALS_KEY_KEYBOARD_INTERRUPT_SAFE] = True
        self.reschedule(task, Value(None))
        return task

    @_public
    async def spawn(self, fn, *args, notify_queues=[]):
        return self.spawn_impl(fn, args, notify_queues=notify_queues)

    ################################################################
    # Outside Context Problems:

    call_soon_queue = attr.ib(default=attr.Factory(stdlib_queue.Queue))
    call_soon_done = attr.ib(default=False)
    # Must be a recursive lock, because it's acquired from signal handlers:
    call_soon_lock = attr.ib(default=attr.Factory(threading.RLock))

    def _call_soon(self, fn, *args, spawn=False):
        with self.call_soon_lock:
            if self.call_soon_done:
                raise RunFinishedError("run() has exited")
            self.call_soon_queue.put_nowait((fn, args, spawn))
        self.io_manager.wakeup_threadsafe()

    @_public
    @_hazmat
    def current_call_soon_thread_and_signal_safe(self):
        return self._call_soon

    async def call_soon_task(self):
        def call_next_or_raise_Empty():
            fn, args, spawn = self.call_soon_queue.get_nowait()
            if spawn:
                task = self.spawn_impl(fn, args)
                if self.crashing:
                    task.cancel_nowait()
            else:
                try:
                    _call_user_fn(fn, *args)
                except BaseException as exc:
                    self.crash(
                        "error in call_soon_thread_and_signal_safe callback",
                        exc)

        try:
            while True:
                try:
                    # Do a bounded amount of work between yields:
                    for _ in range(self.call_soon_queue.qsize()):
                        call_next_or_raise_Empty()
                except stdlib_queue.Empty:
                    await self.io_manager.until_woken()
                else:
                    await yield_briefly()
        except Cancelled:
            with self.call_soon_lock:
                self.call_soon_done = True
            # No more jobs will be submitted, so just clear out any residual
            # ones:
            while True:
                try:
                    call_next_or_raise_Empty()
                except stdlib_queue.Empty:
                    break

def run(fn, *args, clock=None, profilers=[]):
    # Do error-checking up front, before we enter the InternalError try/catch
    if not inspect.iscoroutinefunction(fn):
        raise TypeError("run expected an async function")
    # It wouldn't be *hard* to support nested calls to run(), but I can't
    # think of a single good reason for it, so let's be conservative for
    # now:
    if hasattr(GLOBAL_RUN_CONTEXT, "runner"):
        raise RuntimeError("Attempted to call run() from inside a run()")

    if clock is None:
        clock = SystemClock()
    profilers = list(profilers)
    io_manager = TheIOManager()
    runner = Runner(clock=clock, profilers=profilers, io_manager=io_manager)
    GLOBAL_RUN_CONTEXT.runner = runner
    locals()[LOCALS_KEY_KEYBOARD_INTERRUPT_SAFE] = False

    # This is outside the try/except to avoid a window where KeyboardInterrupt
    # would be allowed and converted into an InternalError:
    with keyboard_interrupt_manager() as keyboard_interrupt_status:
        try:
            with closing(runner):
                # The main reason this is split off into its own function
                # is just to get rid of this extra indentation.
                run_impl(runner, fn, args)
        except BaseException as exc:
            raise InternalError(
                "internal error in trio - please file a bug!") from exc
        finally:
            GLOBAL_RUN_CONTEXT.__dict__.clear()

    result = runner.final_result
    if keyboard_interrupt_status.pending:
        result = Result.combine(result, Error(KeyboardInterrupt()))
    return result.unwrap()

def run_impl(runner, fn, args):
    runner.spawn_impl(runner.call_soon_task, (), type=TaskType.SYSTEM)
    runner.initial_task = runner.spawn_impl(fn, args)

    while runner.tasks:
        if runner.runq:
            timeout = 0
        else:
            deadline = runner.deadlines.keys()[0]
            timeout = runner.clock.deadline_to_sleep_time(deadline)
            # Clamp timeout be fall between 0 and 24 hours. 24 hours is
            # arbitrary, but it avoids issues like people setting timeouts of
            # 10**20 and then getting integer overflows in the underlying
            # system calls, + issues around inf timeouts.
            timeout = min(max(0, timeout), 24 * 60 * 60)

        runner.io_manager.handle_io(timeout)

        now = runner.clock.current_time()
        while runner.deadlines:
            (deadline, _), task = runner.deadlines.peekitem(0)
            if deadline <= now:
                task._fire_timeouts_at(now, TimeoutCancelled())
            else:
                break

        # Process all runnable tasks, but wait for the next iteration
        # before processing tasks that become runnable now. This avoids
        # various starvation issues by ensuring that there's never an
        # unbounded delay between successive checks for I/O.
        for _ in range(len(runner.runq)):
            task = runner.runq.popleft()
            GLOBAL_RUN_CONTEXT.task = task
            for profiler in runner.profilers:
                profiler.before_task_step(task)

            next_send = task._next_send
            task._next_send = None
            try:
                msg = next_send.send(task.coro)
            except StopIteration as stop_iteration:
                runner.task_finished(task, Value(stop_iteration.value))
            except BaseException as task_exc:
                runner.task_finished(task, Error(task_exc))
            else:
                yield_fn, *args = msg
                if yield_fn is yield_briefly:
                    task._cancel_func = lambda: Cancel.SUCCEEDED
                    task._deliver_any_pending_cancel_to_blocked_task()
                    if task._next_send is None:
                        runner.reschedule(task)
                elif yield_fn is yield_briefly_no_cancel:
                    runner.reschedule(task)
                else:
                    assert yield_fn is yield_indefinitely
                    task._cancel_func, = args
                    task._deliver_any_pending_cancel_to_blocked_task()
                del GLOBAL_RUN_CONTEXT.task

            for profiler in runner.profilers:
                profiler.after_task_step(task)

def current_task():
    return GLOBAL_RUN_CONTEXT.task

def current_deadline():
    return GLOBAL_RUN_CONTEXT.task._next_deadline()

@_hazmat
def cancellation_point():
    current_task()._raise_any_pending_cancel()

_WRAPPER_TEMPLATE = """\
def wrapper(*args, **kwargs):
    try:
        meth = GLOBAL_RUN_CONTEXT.{}.{}
    except AttributeError:
        raise RuntimeError("must be called from async context")
    return meth(*args, **kwargs)
"""

def _generate_method_wrappers(cls, path_to_instance):
    for methname, fn in cls.__dict__.items():
        if callable(fn) and getattr(fn, "_public", False):
            # Create a wrapper function that looks up this method in the
            # current thread-local context version of this object, and calls
            # it. exec() is a bit ugly but the resulting code is faster and
            # simpler than doing some loop over getattr.
            ns = {"GLOBAL_RUN_CONTEXT": GLOBAL_RUN_CONTEXT}
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
