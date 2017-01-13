import inspect
import threading
import enum
from collections import deque
from time import monotonic

from sortedcontainers import sorteddict

import oratorio
import oratorio.hazmat
from ._exceptions import (
    InternalError, Cancelled, TaskCancelled, TimeoutCancelled,
    TaskCrashedError)
from ._result import Result, Error, Value
import ._io
from ._api import GLOBAL_RUN_CONTEXT, publish, publish_runner_method

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


# shutdown:
# - a general rule: when you're cancelled it's still legal to spawn children,
# but they need to finish in finite time (imagine they start cancelled)
# - if there's a crash, we cancel all regular tasks (and more tasks might be
# spawned in the future, but they are handled by the rule above)
# - whenever we transition to no regular tasks, we cancel all daemonic tasks
# - when the last daemonic task exits, we exit

# ^^ this is not good enough, because daemon tasks can spawn regular tasks,
# so a crash could cancel all regular tasks, then a new regular task could
# arrive spawned by one of the daemon tasks.
# the rule could be that when we crash, we cancel *all* regular+daemon
# tasks... but I don't like that, because it means that in one this one
# rare case, we create an unusual situation where daemon tasks can be missing,
# which never happens otherwise.
# a different rule could be: daemon tasks can only spawn daemon tasks, never
# regular tasks.


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
TaskType = enum.Enum("TaskType", "SYSTEM REGULAR")

@publish(oratorio)
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
            q = Queue()
            self._result_queues.add(q)
            await q.get()
        return self._task_result

    def join_nowait(self):
        if self._task_result is None:
            raise WouldBlock
        else:
            return self._task_result

# ughh maybe we should just go back to the original masking solution. no
# handler-based solution is going to handle well the case where some runaway
# task is refusing to yield.
def catch_SIGINT(_, _):
    def raise_KeyboardInterrupt():
        raise KeyboardInterrupt
    call_soon_threadsafe(raise_KeyboardInterrupt)
    signal.signal(signal.SIGINT, signal.default_int_handler)
if signal.getsignal(signal.SIGINT) is
signal

async def signal_handler_task(fn, args):
    try:
        if threading.current_thread() == threading.main_thread():
            with catch_signals([signal.SIGINT]) as sigint_queue:
                await spawn(fn, *args)
                await sigint_queue.get()
                raise KeyboardInterrupt
        else:
            await spawn(fn, *args)
    except Cancelled:
        pass

# Container for the stuff that needs to be accessible for what would be
# synchronous traps in curio.
@attr.s(slots=True)
class _Runner:
    _clock = attr.ib()
    _profiler = attr.ib()
    _iomanager = attr.ib()
    _waker = attr.ib()

    _runq = attr.ib(default=attr.Factory(deque))
    _tasks = attr.ib(default=attr.Factory(set))
    _regular_task_count = attr.ib(default=0)

    # {(deadline, id(task)): task with non-null deadline}
    _deadlines = attr.ib(default=attr.Factory(sorteddict))

    _initial_task = attr.ib(default=None)
    _final_result = attr.ib(default=None)
    _crashing = attr.ib(default=False)

    _call_soon_queue = attr.ib(default=attr.Factory(deque))

    def close(self):
        self._profiler.close()
        self._iomanager.close()
        self._waker.close()

    def _crash(self, exc):
        # XX ergonomics: maybe KeyboardInterrupt should be preserved instead
        # of being wrapped?
        wrapper = TaskCrashedError()
        wrapper.__cause__ = exc
        self._final_result = Result.combine(self._final_result, Error(wrapper))
        if not self._crashing:
            self._crashing = True
            for task in self._tasks:
                if task._type is TaskType.REGULAR:
                    task.cancel_nowait()

    def _task_finished(self, task, result):
        self._tasks.remove(task)

        if task._type is TaskType.REGULAR:
            self._regular_task_count -= 1
            if not self._regular_task_count:
                # The last REGULAR task just exited, so we're done; cancel
                # everything.
                for other_task in self._tasks:
                    other_task.cancel_nowait()

        if task is initial_task:
            self._final_result = Result.combine(self._final_result, result)
            # Avoid pinning the Task object in memory:
            self._initial_task = None
        elif type(result) is Error and not task.result_queues:
            if task._type is TaskType.REGULAR:
                self._crash(result.error)
            else:
                # Propagate system task crashes out, to eventually raise an
                # InternalError.
                assert task._type is TaskType.SYSTEM
                result.unwrap()

        for result_queue in task.result_queues:
            try:
                result_queue.put_nowait(task)
            except BaseException as exc:
                self._crash(exc)

    async def _call_soon_task(self):
        while True:
            await self._waker.until_woken()
            while True:
                # deque methods are documented to be thread-safe
                fn, args = self._call_soon_queue.popleft()
                try:
                    fn(*args)
                except BaseException as exc:
                    self._crash(exc)
                # XX do a sleep(0)

    def _call_soon_threadsafe(self, fn, *args):
        # deque methods are documented to be thread-safe
        self._call_soon_queue.append((fn, args))
        self._waker.wakeup_threadsafe()

    @publish_runner_method(oratorio.hazmat)
    def current_call_soon_threadsafe_func(self):
        return self._call_soon_threadsafe

    @publish_runner_method(oratorio)
    def current_time(self):
        return self._clock.current_time()

    @publish_runner_method(oratorio)
    def current_profiler(self):
        return self._profiler

    @publish_runner_method(oratorio.hazmat)
    def reschedule(self, task, next_send=Value(None)):
        assert task._next_send is None
        task.state = "RUNNABLE"
        task._next_send = next_send
        task._interrupt = None
        self._runq.append(task)

    def _spawn(self, fn, args, *, type=TaskType.REGULAR, result_queues=[]):
        if not inspect.iscoroutinefunction(fn):
            raise TypeError("expected an async function")
        coro = fn(*args)
        task = Task(_type=type, coro=coro, result_queues=result_queues)
        self._tasks.add(task)
        if type is TaskType.REGULAR:
            self._regular_task_count += 1
        self.reschedule(task, Value(None))
        return task

    @publish_runner_method(oratorio)
    def spawn(self, fn, args, *, result_queues=[]):
        return self._spawn(fn, args, result_queues=result_queues)

@publish(oratorio)
def run(fn, *args, *, clock=None, profiler=None):
    if clock is None:
        clock = SystemClock()
    if profiler is None:
        profiler = NullProfiler()

    # XX iomanager
    # XX threadsafe_waker

    runner = _Runner(_clock=clock, _profiler=profiler)

    # It wouldn't be *hard* to support nested calls to run(), but I can't
    # think of a single good reason for it, so let's be conservative for now:
    if hasattr(GLOBAL_RUN_CONTEXT, "runner"):
        raise RuntimeError("Attempted to call run() from inside a run()")
    GLOBAL_RUN_CONTEXT.runner = runner

    try:
        with closing(runner):
            # The main reason this is split off into its own function is just
            # to get rid of this extra indentation.
            _run(runner, fn, args)
    except BaseException as exc:
        raise InternalError(
            "internal error in oratorio - please file a bug!") from exc
    finally:
        GLOBAL_RUN_CONTEXT.__dict__.clear()

    return runner._final_result.unwrap()

def _clamp(low, value, high):
    return min(max(low, value), high)

def _run(runner, fn, args):
    # Hide this giant function from pytest tracebacks
    __tracebackhide__ = True

    runner._spawn(runner._call_soon_threadsafe, type=TaskType.SYSTEM)
    # This task takes responsibility for spawning the initial task, after it's
    # set up the initial signal-handling stuff:
    runner._spawn(runner._signal_handler_task, fn, args, type=TaskType.SYSTEM)

    while runner._tasks:
        if runner._runq:
            timeout = 0
        elif runner._deadlines:
            deadline = runner._deadlines.keys()[0]
            timeout = runner._clock.deadline_to_sleep_time(deadline))
            # 24 hours is arbitrary, but "long enough" that the spurious
            # wakeups it introduces shouldn't matter, and it avoids any
            # possible issue with integer overflow in the underlying system
            # calls (protects against people setting timeouts of 10**20 or
            # whatever).
            timeout = _clamp(0, timeout, 24 * 60 * 60)
        else:
            timeout = -1

        runner._iomanager.poll(timeout)

        # Process all runnable tasks, but wait for the next iteration
        # before processing tasks that become runnable now. This avoids
        # various starvation issues by ensuring that there's never an
        # unbounded delay between successive checks for I/O.
        for _ in range(len(self._runq)):
            task = self._runq.popleft()
            GLOBAL_RUN_CONTEXT.task = task
            profiler.before_task_step(task)
            next_send = task._next_send
            task._next_send = None
            try:
                msg = next_send.send(task.coro)
            except StopIteration as stop_iteration:
                runner._task_finished(task, Value(stop_iteration.value))
            except BaseException as task_exc:
                runner._task_finished(task, Error(task_exc))

            # blocking trap
            profiler.after_task_step(task)
            # XX
            task.interrupt_func, task.state = msg
            # check for cancellation
            # on windows, have to check for cancellation before issuing the
            # I/O commands... so just do that I guess.
            #
            # run the trap
            del GLOBAL_RUN_CONTEXT.task

@publish(oratorio)
def current_task():
    return GLOBAL_RUN_CONTEXT.task
