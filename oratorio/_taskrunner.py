import inspect
import threading
import itertools
from collections import deque
from time import monotonic

import sortedcontainers

from ._signal import sigmask
from ._result import Result, Error, Value

class WouldBlock(Exception):
    pass

class Cancelled(Exception):
    partial_result = None
    interrupt = None  # XX

@attr.s
class SendallPartialResult:
    bytes_sent = attr.ib()

class TaskCancelled(Cancelled):
    pass

class TimeoutCancelled(Cancelled):
    pass


class SystemClock:
    def now(self):
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

_task_counter = itertools.count()

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

# Result etc. are public; join returns one of them. This distinguishes between
# errors in join/join_nowait (e.g. WouldBlock) versus errors inside the task.

# crashes are wrapped in a TaskCrashedError with __cause__
# any exceptions inside actual runner are converted into InternalError (bug!)

# final result is... a Result? or do we unwrap it?

# spawn being synchronous -> you can write
#    task = await spawn(...)
#    task.join()
# and that's guaranteed not to crash, because join is listening

# maybe *all* synchronous traps are actually method calls on a thread-local
# global, except for spawn() (because it calls an async function)?
#
# and we can have a call_soon_threadsafe as the low-level primitive, maybe have
# a call_from_thread that blocks (!) the thread as the preferred option.

class Task:
    def __init__(self, coro, daemon, result_qs=[]):
        self.coro = coro
        self.daemon = daemon
        self._task_result = None
        self._next_send = None
        self._result_queues = set(result_queues)
        self._interrupt_func = None
        self._cancel_stack = []

    def cancel_nowait(self, exc=None):
        if exc is None:
            exc = TaskCancelled()
        self.cancel_interrupt.fire(exc)

    def add_result_queue(self, result_queue):
        if result_queue in self._result_queues:
            raise ValueError("can't add same result queue twice")
        self._result_queues.add(result_queue)
        if self._task_result is not None:
            result_queue.put_nowait(self)

    def remove_result_queue(self, result_q):
        self._result_queues.remove(result_q)

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


_GLOBAL_RUN_CONTEXT = threading.local()

class InternalError(Exception):
    pass

# Container for the stuff that needs to be accessible for what would be
# synchronous traps in curio.
@attr.s(slots=True)
class _TaskRunner:
    _clock = attr.ib()
    _profiler = attr.ib()
    _runq = attr.ib(default=attr.Factory(deque))
    _regular_tasks = attr.ib(default=attr.Factory(set))
    _daemon_tasks = attr.ib(default=attr.Factory(set))

    # These are the underlying implementions for the corresponding
    # user-exposed primitives:
    def now(self):
        return self._clock.now()

    def profiler(self):
        return self._profiler

    def reschedule(self, task, next_send):
        assert task._next_send is None
        task._next_send = next_send
        task._interrupt = None
        self._runq.append(task)

    def _task_set_for(self, task):
        if task.daemon:
            return self._daemon_tasks
        else:
            return self._regular_tasks

    def spawn(self, fn, args, *, daemon):
        if not inspect.iscoroutinefunction(fn):
            raise TypeError("spawn expected an async function")
        coro = fn(*args)
        task = Task(coro, daemon)
        self._task_set_for(task).add(task)
        self.reschedule(task, Value(None))
        return task

def run(fn, *args, *, clock=None, profiler=None):
    if clock is None:
        clock = SystemClock()
    if profiler is None:
        profiler = NullProfiler()
    runner = _TaskRunner(_clock=clock, _profiler=profiler)

    if hasattr(_GLOBAL_RUN_CONTEXT, "runner"):
        raise RuntimeError("Attempted to call run() from inside a run()")
    _GLOBAL_RUN_CONTEXT.runner = runner

    try:
        with closing(profiler), \
             sigmask(signal.SIG_BLOCK, signal.SIGINT) as original_sigmask:
            # The main reason this is split off into its own function is just
            # to get rid of this extra indentation.
            result = _run(fn, args, runner, original_sigmask)
    except BaseException as exc:
        raise InternalError from exc
    finally:
        _GLOBAL_RUN_CONTEXT.__dict__.clear()

    return result.unwrap()

def _run(fn, args, runner, original_sigmask):
    # Hide this giant function from pytest tracebacks
    __tracebackhide__ = True

    initial_task = runner.spawn(fn, args, daemon=False)
    final_result = None
    crash_unwinding = False

    def panic(exc):
        nonlocal crash_unwinding
        wrapper = TaskCrashedError()
        wrapper.__cause__ = exc
        final_result = Result.combine(final_result, Error(wrapper))
        if not crash_unwinding:
            crash_unwinding = True
            for task in runner._regular_tasks:
                task.cancel_nowait()

    def task_finished(task, result):
        nonlocal final_result, crashed

        task._task_result = Value(stop_iteration.value)

        runner._task_set_for(task).remove(task)
        if not task.daemon and not runner._regular_tasks:
            # The last regular task just exited
            for daemon in runner._daemon_tasks:
                daemon.cancel_nowait()

        if task is initial_task:
            final_result = Result.combine(final_result, result)
        elif type(result) is Error and not task._result_queues:
            panic(result.error)

        for result_queue in task._result_queues:
            try:
                result_queue.put_nowait(task)
            except BaseException as exc:
                panic(exc)

    while runner._regular_tasks or runner._daemon_tasks:
        # Process all runnable tasks, but wait for the next iteration
        # before processing tasks that become runnable now. This avoids
        # various starvation issues by ensuring that there's never an
        # unbounded delay between successive checks for I/O.
        for _ in range(len(self._runq)):
            task = self._runq.popleft()
            _GLOBAL_RUN_CONTEXT.task = task
            profiler.before_task_step(task)
            next_send = task._next_send
            task._next_send = None
            try:
                with sigmask(signal.SIG_SETMASK, original_mask):
                    msg = next_send.send(task.coro)
            except StopIteration as stop_iteration:
                task_finished(task, Value(stop_iteration.value))
            except BaseException as task_exc:
                task_finished(task, Error(task_exc))

            # blocking trap
            profiler.after_task_step(task)
            # XX
            # check for cancellation
            # run the trap
            del _GLOBAL_RUN_CONTEXT.task
