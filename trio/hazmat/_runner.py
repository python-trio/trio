import inspect
import enum
from collections import deque
import threading
import queue as stdlib_queue
from time import monotonic
import os

from sortedcontainers import sorteddict

from ._exceptions import (
    InternalError, Cancelled, TaskCancelled, TimeoutCancelled,
    TaskCrashedError)
from ._result import Result, Error, Value
from . import _public

# Re-exported as trio.hazmat.* and trio.*
__all__ = ["Task", "run"]

_GLOBAL_RUN_CONTEXT = _threading.local()

if os.name == "nt":
    from ._io_windows import IOCPIOManager as TheRunManager
else:
    try:
        from ._io_unix import EpollIOManager as TheRunManager
    except ImportError:
        try:
            from ._io_unix import KqueueIOManager as TheRunManager
        except ImportError:
            raise NotImplementedError("unsupported platform")

class SystemClock:
    def current_time(self):
        return monotonic()

    def deadline_to_sleep_time(self, deadline):
        return deadline - monotonic()

class NullProfiler:
    def before_task_step(self, task):
        pass

    def after_task_step(self, task):
        pass

    def close(self):
        pass

@attr.s(slots=True)
class Timeout:
    task = @attr.ib()
    deadline = @attr.ib()

# cancel stack is:
# - the root Task.cancel_nowait token
# - timeout_after tokens
#
# operations:
async with cancel_after(...) as timed_out:
    ...
if timed_out:
    ...

await current_deadline()

async with mask_cancellations as mask:
    ...
    async with unmask_cancellations(mask):
        ...

    if mask.cancelled...?

# what should we do with code like:
async with mask_cancellations as mask:
    async with timeout_after(...):
        async with unmask_cancellations(mask):
            ...
# how about:
async with mask_cancellations as mask1:
    async with timeout_after(...):
        async with mask_cancellations as mask2:
            async with unmask_cancellations(mask1):
                ...
# maybe the rule is that unmask must always be nested *directly* inside the
# matching mask, with no intervening mask or tokens?
# and in that same scope maybe we can allow explicit polling? is explicit
# polling even any use?
#
# Looking carefully at _supervise_loop, it looks like if we can make cancel
# and join sync-colored, then we can actually make the *only* 'await' call the
# one that we want to be interruptible.
#
# maybe 'async with assert_no_blocking', 'async with assert_blocking'?
#
# I still like the cancellation stack and the idea that once cancellation N
# has fired we disable cancellations N+1 and higher.


# when a cancellation fires we disable all items higher on the stack -- but
# new ones can still be added.


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

@attr.s(slots=True)
class Task:
    _type = attr.ib()
    coro = attr.ib()
    result_queues = attr.ib(convert=set, repr=False)
    # This is for debugging tools only to give a hint as to what code is
    # doing:
    state = attr.ib(default=None)
    _task_result = attr.ib(default=None, repr=False)
    # tasks start out unscheduled, and unscheduled tasks have None here
    _next_send = attr.ib(default=None, repr=False)
    _interrupt_func = attr.ib(default=None, repr=False)
    _cancel_stack = attr.ib(default=attr.Factory(list), repr=False)

    def cancel_nowait(self, exc=None):
        if exc is None:
            exc = TaskCancelled()
        self.cancel_interrupt.fire(exc)

    def join(self):
        if self._task_result is None:
            # XX maybe write this differently
            q = Queue()
            self.result_queues.add(q)
            await q.get()
        return self._task_result

    def join_nowait(self):
        if self._task_result is None:
            raise WouldBlock
        else:
            return self._task_result

# Container for the stuff that needs to be accessible for what would be
# synchronous traps in curio.
@attr.s(slots=True)
class _Runner:
    clock = attr.ib()
    profiler = attr.ib()
    io_manager = attr.ib()

    runq = attr.ib(default=attr.Factory(deque))
    tasks = attr.ib(default=attr.Factory(set))
    regular_task_count = attr.ib(default=0)

    # {(deadline, id(task)): task with non-null deadline}
    deadlines = attr.ib(default=attr.Factory(sorteddict))

    initial_task = attr.ib(default=None)
    final_result = attr.ib(default=None)
    crashing = attr.ib(default=False)

    def close(self):
        self.profiler.close()
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

        if task is initial_task:
            self.final_result = Result.combine(self.final_result, result)
            # Avoid pinning the Task object in memory:
            self.initial_task = None
        elif type(result) is Error and not task.result_queues:
            if task._type is TaskType.REGULAR:
                self.crash("unwatched task raised exception", result.error)
            else:
                # Propagate system task crashes out, to eventually raise an
                # InternalError.
                assert task._type is TaskType.SYSTEM
                result.unwrap()

        for result_queue in task.result_queues:
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
    def current_profiler(self):
        return self.profiler

    @_public
    def reschedule(self, task, next_send=Value(None)):
        assert task._next_send is None
        task.state = "RUNNABLE"
        task._next_send = next_send
        task._interrupt = None
        self.runq.append(task)

    def spawn_impl(self, fn, args, *, type=TaskType.REGULAR, result_queues=[]):
        if not inspect.iscoroutinefunction(fn):
            raise TypeError("spawn expected an async function")
        coro = fn(*args)
        task = Task(_type=type, coro=coro, result_queues=result_queues)
        self.tasks.add(task)
        if type is TaskType.REGULAR:
            self.regular_task_count += 1
        self.reschedule(task, Value(None))
        return task

    @_public
    async def spawn(self, fn, *args, *, result_queues=[]):
        return self.spawn_impl(fn, args, result_queues=result_queues)

    ################################################################
    # Outside Context Problems:

    call_soon_queue = attr.ib(default=attr.Factory(stdlib_queue.Queue))
    call_soon_done = attr.ib(default=False)
    # Must be a recursive lock, because it's acquired from signal handlers:
    call_soon_lock = attr.ib(default=attr.Factory(threading.RLock))

    def _call_soon(self, fn, *args, *, spawn=False):
        with self.call_soon_lock:
            if self.call_soon_done:
                raise RuntimeError("run() has exited")
            self.call_soon_queue.put_nowait((fn, args, spawn))
        self.io_manager.wakeup_threadsafe()

    @_public
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
                    fn(*args)
                except BaseException as exc:
                    self.crash(
                        "error in call_soon_thread_and_signal_safe callback",
                        exce)

        try:
            while True:
                try:
                    # Do a bounded amount of work between yields:
                    for _ in range(self.call_soon_queue.qsize()):
                        call_next_or_raise_Empty()
                except stdlib_queue.Empty:
                    await self.io_manager.until_woken()
                else:
                    await XX sched_yield
        except Cancelled:
            with self._shutdown_lock:
                self._done = True
            # No more jobs will be submitted, so just clear out any residual
            # ones:
            while True:
                try:
                    call_next_or_raise_Empty()
                except stdlib_queue.Empty:
                    break

def run(fn, *args, *, clock=None, profiler=None):
    # Do error-checking up front, before we enter the InternalError try/catch
    if not inspect.iscoroutinefunction(fn):
        raise TypeError("run expected an async function")
    # It wouldn't be *hard* to support nested calls to run(), but I can't
    # think of a single good reason for it, so let's be conservative for
    # now:
    if hasattr(_GLOBAL_RUN_CONTEXT, "runner"):
        raise RuntimeError("Attempted to call run() from inside a run()")

    try:
        if clock is None:
            clock = SystemClock()
        if profiler is None:
            profiler = NullProfiler()
        io_manager = TheIOManager()
        runner = _Runner(clock=clock, profiler=profiler, io_manager=io_manager)
        _GLOBAL_RUN_CONTEXT.runner = runner

        with closing(runner):
            # The main reason this is split off into its own function is just
            # to get rid of this extra indentation.
            _run(runner, fn, args)
    except BaseException as exc:
        raise InternalError(
            "internal error in trio - please file a bug!") from exc
    finally:
        _GLOBAL_RUN_CONTEXT.__dict__.clear()

    return runner._final_result.unwrap()

def _run(runner, fn, args):
    runner._spawn_impl(runner._call_soon_task, (), type=TaskType.SYSTEM)
    runner._spawn_impl(fn, args)

    while runner.tasks:
        if runner.runq:
            timeout = 0
        elif runner.deadlines:
            deadline = runner.deadlines.keys()[0]
            timeout = runner.clock.deadline_to_sleep_time(deadline))
            # Clamp timeout be fall between 0 and 24 hours. 24 hours is
            # arbitrary, but it avoids issues like people setting timeouts of
            # 10**20 and then getting integer overflows in the underlying
            # system calls.
            timeout = min(max(0, timeout), 24 * 60 * 60)
        else:
            timeout = -1

        runner.io_manager.handle_io(timeout)

        # Process all runnable tasks, but wait for the next iteration
        # before processing tasks that become runnable now. This avoids
        # various starvation issues by ensuring that there's never an
        # unbounded delay between successive checks for I/O.
        for _ in range(len(runner.runq)):
            task = runner.runq.popleft()
            _GLOBAL_RUN_CONTEXT.task = task
            runner.profiler.before_task_step(task)
            next_send = task._next_send
            task._next_send = None
            try:
                msg = next_send.send(task.coro)
            except StopIteration as stop_iteration:
                runner.task_finished(task, Value(stop_iteration.value))
            except BaseException as task_exc:
                runner.task_finished(task, Error(task_exc))

            # blocking trap
            runner.profiler.after_task_step(task)
            # XX
            task.interrupt_func, task.state = msg
            # check for cancellation
            # on windows, have to check for cancellation before issuing the
            # I/O commands... so just do that I guess.
            #
            # run the trap
            del _GLOBAL_RUN_CONTEXT.task
