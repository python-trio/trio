import inspect
import threading
import itertools
import enum
from collections import deque
from time import monotonic

from sortedcontainers import sorteddict

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
# and we can have a call_soon_threadsafe as the low-level primitive, maybe
# have a call_from_thread that blocks (!) the thread as the preferred option.
# NB to handle async acquisition of threading locks we need to be able to
# issue multiple calls on the same thread. (curio abide() handles exactly
# these two cases: sync call and sync context manager). So maybe a
# WorkerThread primitive is best?

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


_GLOBAL_RUN_CONTEXT = threading.local()

class InternalError(Exception):
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

    def close(self):
        self._profiler.close()
        self._iomanager.close()

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

    # These are the underlying implementions for the corresponding
    # user-exposed primitives:
    def now(self):
        return self._clock.now()

    def profiler(self):
        return self._profiler

    def reschedule(self, task, next_send=Value(None)):
        assert task._next_send is None
        task.state = "RUNNABLE"
        task._next_send = next_send
        task._interrupt = None
        self._runq.append(task)

    def spawn(self, fn, args, *, type, result_queues=[]):
        if not inspect.iscoroutinefunction(fn):
            raise TypeError("spawn expected an async function")
        coro = fn(*args)
        task = Task(_type=type, coro=coro, result_queues=result_queues)
        self._tasks.add(task)
        if type is TaskType.REGULAR:
            self._regular_task_count += 1
        self.reschedule(task, Value(None))
        return task

def run(fn, *args, *, clock=None, profiler=None):
    if clock is None:
        clock = SystemClock()
    if profiler is None:
        profiler = NullProfiler()

    # XX iomanager
    # maybe XX threadsafe_waker

    runner = _Runner(_clock=clock, _profiler=profiler)

    # It wouldn't be *hard* to support nested calls to run(), but I can't
    # think of a single good reason for it, so let's play it safe...
    if hasattr(_GLOBAL_RUN_CONTEXT, "runner"):
        raise RuntimeError("Attempted to call run() from inside a run()")
    _GLOBAL_RUN_CONTEXT.runner = runner

    try:
        with closing(runner), \
             sigmask(signal.SIG_BLOCK, signal.SIGINT) as original_sigmask:
            # The main reason this is split off into its own function is just
            # to get rid of this extra indentation.
            result = _run(fn, args, runner, original_sigmask)
    except BaseException as exc:
        raise InternalError from exc
    finally:
        _GLOBAL_RUN_CONTEXT.__dict__.clear()

    return result.unwrap()

def _clamp(low, value, high):
    return min(max(low, value), high)

def _run(fn, args, runner, original_sigmask):
    # Hide this giant function from pytest tracebacks
    __tracebackhide__ = True

    initial_task = runner.spawn(fn, args, type=TaskType.REGULAR)
    final_result = None
    crash_unwinding = False

    # XX two system tasks:
    # - watch for cross-thread/signal wakeups
    # - watch for SIGINT and raise KeyboardInterrupt (iff running on main
    #   thread)

    while runner._tasks:
        if runner._runq:
            timeout = 0
        elif runner._deadlines:
            deadline = runner._deadlines.keys()[0]
            timeout = runner._clock.deadline_to_sleep_time(deadline))
            # 24 hours is arbitrary, but "long enough" that the spurious
            # wakeups it introduces shouldn't matter, and it avoids any
            # possible issue with integer overflow in the underlying system
            # calls.
            timeout = _clamp(0, timeout, 24 * 60 * 60)
        else:
            timeout = -1

        try:
            with sigmask(signal.SIG_SETMASK, original_mask):
                runner._iomanager.poll(timeout)
        except KeyboardInterrupt as exc:
            runner._crash(exc)

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
                    # XX if the signal mask *changed* we want to preserve
                    # that... should capture a new value for original_mask
                    # here, or something like that.
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
            del _GLOBAL_RUN_CONTEXT.task
