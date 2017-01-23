import abc
import inspect
import enum
from collections import deque
import threading
from time import monotonic
import os
import random
from contextlib import contextmanager, closing

import attr
from sortedcontainers import SortedDict

from .. import _core
from ._exceptions import (
    UnhandledExceptionError, TrioInternalError, RunFinishedError,
    Cancelled, TaskCancelled, TimeoutCancelled, WouldBlock
)
from ._result import Result, Error, Value
from ._traps import (
    yield_briefly_no_cancel, Abort, yield_indefinitely,
)
from ._keyboard_interrupt import (
    LOCALS_KEY_KEYBOARD_INTERRUPT_SAFE, keyboard_interrupt_manager,
)
from ._cancel import CancelStack, yield_briefly
from . import _public, _hazmat

# At the bottom of this file there's also some "clever" code that generates
# wrapper functions for runner and io manager methods, and adds them to
# __all__. These are all re-exported as part of the 'trio' or 'trio.hazmat'
# namespaces.
__all__ = ["Clock", "Instrument", "Task", "run",
           "current_task", "current_deadline", "yield_if_cancelled"]

GLOBAL_RUN_CONTEXT = threading.local()


if os.name == "nt":
    from ._io_windows import WindowsIOManager as TheIOManager
else:
    try:
        from ._io_unix import EpollIOManager as TheIOManager
    except ImportError:
        try:
            from ._io_unix import KqueueIOManager as TheIOManager
        except ImportError:  # pragma: no cover
            raise NotImplementedError("unsupported platform")


class Clock(abc.ABC):
    @abc.abstractmethod
    def current_time(self):  # pragma: no cover
        pass

    @abc.abstractmethod
    def deadline_to_sleep_time(self, deadline):  # pragma: no cover
        pass

_r = random.Random()
@attr.s(slots=True, frozen=True)
class SystemClock(Clock):
    # Add a large random offset to our clock to ensure that if people
    # accidentally call time.monotonic() directly or start comparing clocks
    # between different runs, then they'll notice the bug quickly:
    offset = attr.ib(default=attr.Factory(lambda: _r.uniform(10000, 200000)))

    def current_time(self):
        return self.offset + monotonic()

    def deadline_to_sleep_time(self, deadline):
        return deadline - self.current_time()


class Instrument(abc.ABC):
    def task_scheduled(self, task):
        pass

    def before_task_step(self, task):
        pass

    def after_task_step(self, task):
        pass

    def close(self):
        pass


# The rules:
#
# - When all REGULAR tasks have exited, we cancel all SYSTEM tasks.
# - If a REGULAR task crashes, we cancel all REGULAR tasks (once).
# - If a SYSTEM task crashes we exit immediately with TrioInternalError.
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
    _abort_func = attr.ib(default=None, repr=False)

    def add_notify_queue(self, queue):
        if queue in self._notify_queues:
            raise ValueError("can't add same notify queue twice")
        if self._task_result is not None:
            queue.put_nowait(self)
        else:
            self._notify_queues.add(queue)

    def discard_notify_queue(self, queue):
        self._notify_queues.discard(queue)

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

    def _fire_expired_timeouts(self, now, exc):
        with self._might_adjust_deadline():
            self._cancel_stack.fire_expired_timeouts(self, now, exc)

    def _deliver_any_pending_cancel_to_blocked_task(self):
        with self._might_adjust_deadline():
            self._cancel_stack.deliver_any_pending_cancel_to_blocked_task(self)

    def _has_pending_cancel(self):
        return self._cancel_stack.has_pending_cancel()

    def cancel(self, exc=None):
        # XX Not sure if this pickiness is useful, but easier to start
        # strict and maybe relax it later...
        if self._task_result is not None:
            raise RuntimeError("can't cancel a task that has already exited")
        if exc is None:
            exc = TaskCancelled()
        with self._might_adjust_deadline():
            self._cancel_stack.fire_task_cancel(self, exc)

    def join_nowait(self):
        if self._task_result is None:
            raise WouldBlock
        else:
            return self._task_result

    async def join(self):
        if self._task_result is None:
            q = _core.Queue(1)
            self.add_notify_queue(q)
            try:
                await q.get()
            finally:
                self.discard_notify_queue(q)
        assert self._task_result is not None
        return self._task_result


@attr.s(frozen=True)
class _RunStatistics:
    tasks_living = attr.ib()
    tasks_runnable = attr.ib()
    unhandled_exception = attr.ib()
    seconds_to_next_deadline = attr.ib()
    io_statistics = attr.ib()
    call_soon_queue_size = attr.ib()

@attr.s(cmp=False, hash=False)
class Runner:
    clock = attr.ib()
    instruments = attr.ib()
    io_manager = attr.ib()

    runq = attr.ib(default=attr.Factory(deque))
    tasks = attr.ib(default=attr.Factory(set))
    regular_task_count = attr.ib(default=0)
    r = attr.ib(default=attr.Factory(random.Random))

    # {(deadline, id(task)): task}
    # only contains tasks with non-infinite deadlines
    deadlines = attr.ib(default=attr.Factory(SortedDict))

    initial_task = attr.ib(default=None)
    unhandled_exception_result = attr.ib(default=None)

    @_public
    def current_statistics(self):
        if self.deadlines:
            next_deadline, _ = self.deadlines.keys()[0]
            seconds_to_next_deadline = next_deadline - self.current_time()
        else:
            seconds_to_next_deadline = float("inf")
        return _RunStatistics(
            tasks_living=len(self.tasks),
            tasks_runnable=len(self.runq),
            unhandled_exception=(self.unhandled_exception_result is not None),
            seconds_to_next_deadline=seconds_to_next_deadline,
            io_statistics=self.io_manager.statistics(),
            call_soon_queue_size=len(self.call_soon_queue),
        )

    def close(self):
        self.io_manager.close()
        self.instrument("close")

    def instrument(self, method, *args):
        bad = []
        for i, instrument in enumerate(self.instruments):
            try:
                getattr(instrument, method)(*args)
            except BaseException as exc:
                self.crash("error in instrument {!r}.{}"
                           .format(instrument, method),
                           exc)
                bad.append(i)
        while bad:
            del self.instruments[bad.pop()]

    def crash(self, message, exc):
        # XX ergonomics: maybe KeyboardInterrupt should be preserved instead
        # of being wrapped?
        wrapper = UnhandledExceptionError(message)
        wrapper.__cause__ = exc
        if self.unhandled_exception_result is None:
            # This is the first unhandled exception, so cancel everything
            for task in self.tasks:
                if task._type is TaskType.REGULAR:
                    task.cancel()
        self.unhandled_exception_result = Result.combine(
            self.unhandled_exception_result, Error(wrapper))

    def task_finished(self, task, result):
        task._task_result = result
        self.tasks.remove(task)

        if task._type is TaskType.REGULAR:
            self.regular_task_count -= 1
            if not self.regular_task_count:
                # The last REGULAR task just exited, so we're done; cancel
                # everything.
                for other_task in self.tasks:
                    other_task.cancel()

        notified = False
        while task._notify_queues:
            notify_queue = task._notify_queues.pop()
            try:
                notify_queue.put_nowait(task)
            except BaseException as exc:
                self.crash("error notifying task watcher of task exit", exc)
            else:
                notified = True

        if type(result) is Error:
            if task._type is TaskType.SYSTEM:
                # System tasks should *never* crash. If they do, propagate it
                # out to eventually raise an TrioInternalError.
                result.unwrap()
            elif not notified and task is not self.initial_task:
                self.crash("unwatched task raised exception", result.error)

    # Methods marked with @_public get converted into functions exported by
    # trio.hazmat:
    @_public
    def current_time(self):
        return self.clock.current_time()

    @_public
    def current_instruments(self):
        return self.instruments

    @_public
    @_hazmat
    def reschedule(self, task, next_send=Value(None)):
        assert task._runner is self
        assert task._next_send is None
        task._next_send = next_send
        task._abort_func = None
        self.runq.append(task)
        self.instrument("task_scheduled", task)

    def spawn_impl(self, fn, args, *, type=TaskType.REGULAR, notify_queues=[]):
        coro = fn(*args)
        if not inspect.iscoroutine(coro):
            raise TypeError("spawn expected an async function")
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

    # This used to use a queue.Queue. but that was broken, because Queues are
    # implemented in Python, and not reentrant -- so it was thread-safe, but
    # not signal-safe. deque is implemented in C, so each operation is atomic
    # WRT threads (and this is guaranteed in the docs), AND each operation is
    # atomic WRT signal delivery (signal handlers can run on either side, but
    # not *during* a deque operation).
    call_soon_queue = attr.ib(default=attr.Factory(deque))
    call_soon_done = attr.ib(default=False)
    # Must be a reentrant lock, because it's acquired from signal
    # handlers. RLock is signal-safe as of cpython 3.2:
    #     https://bugs.python.org/issue13697#msg237140
    call_soon_lock = attr.ib(default=attr.Factory(threading.RLock))

    def call_soon_thread_and_signal_safe(self, fn, *args, spawn=False):
        with self.call_soon_lock:
            if self.call_soon_done:
                raise RunFinishedError("run() has exited")
            # We have to hold the lock all the way through here, because
            # otherwise the main thread might exit *while* we're doing these
            # calls, and then our queue item might not be processed, or the
            # wakeup call might trigger an OSError b/c the IO manager has
            # already been shut down.
            self.call_soon_queue.append((fn, args, spawn))
            self.io_manager.wakeup_threadsafe()

    @_public
    @_hazmat
    def current_call_soon_thread_and_signal_safe(self):
        return self.call_soon_thread_and_signal_safe

    async def call_soon_task(self):
        # Returns True if it managed to do some work, and false if the queue
        # was empty.
        def maybe_call_next():
            try:
                fn, args, spawn = self.call_soon_queue.popleft()
            except IndexError:
                return False  # queue empty
            if spawn:
                # XX make this run with KeyboardInterrupt *disabled*
                # and leave it up to the code using it to enable it if wanted
                # maybe call_with/out_ki(...)
                # and acall_with/out_ki(...)?
                task = self.spawn_impl(fn, args)
                # If we're in the middle of crashing, then immediately cancel:
                if self.unhandled_exception_result is not None:
                    task.cancel()
            else:
                try:
                    # We don't renable KeyboardInterrupt here, because
                    # run_in_trio_thread wants to wait until it actually
                    # reaches user code before enabling them.
                    fn(*args)
                except BaseException as exc:
                    self.crash(
                        "error in call_soon_thread_and_signal_safe callback",
                        exc)
            return True

        try:
            while True:
                # Do a bounded amount of work between yields.
                # We always want to try processing at least one, though;
                # otherwise we could just loop around doing nothing at
                # all. If the queue is really empty, we'll get an
                # exception and go to sleep until woken.
                for _ in range(max(1, len(self.call_soon_queue))):
                    if not maybe_call_next():
                        await self.io_manager.wait_woken()
                        break
                else:
                    await yield_briefly()
        except Cancelled:
            with self.call_soon_lock:
                self.call_soon_done = True
            # No more jobs will be submitted, so just clear out any residual
            # ones:
            while maybe_call_next():
                pass

    ################################################################
    # Quiescing
    #
    waiting_for_idle = attr.ib(default=attr.Factory(set))

    @_public
    @_hazmat
    async def wait_run_loop_idle(self):
        task = current_task()
        self.waiting_for_idle.add(task)
        def abort():
            self.waiting_for_idle.remove(task)
            return Abort.SUCCEEDED
        await yield_indefinitely(abort)


def run(fn, *args, clock=None, instruments=[]):
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
    runner = Runner(clock=clock, instruments=instruments, io_manager=io_manager)
    GLOBAL_RUN_CONTEXT.runner = runner
    locals()[LOCALS_KEY_KEYBOARD_INTERRUPT_SAFE] = False

    def ki_cb(status):
        def raise_KeyboardInterrupt():
            status.pending = False
            raise KeyboardInterrupt
        try:
            runner.call_soon_thread_and_signal_safe(raise_KeyboardInterrupt)
        except RunFinishedError:
            pass

    # This is outside the try/except to avoid a window where KeyboardInterrupt
    # would be allowed and converted into an TrioInternalError:
    try:
        with keyboard_interrupt_manager(ki_cb) as ki_status:
            try:
                with closing(runner):
                    # The main reason this is split off into its own function
                    # is just to get rid of this extra indentation.
                    result = run_impl(runner, fn, args)
            except BaseException as exc:
                raise TrioInternalError(
                    "internal error in trio - please file a bug!") from exc
            finally:
                GLOBAL_RUN_CONTEXT.__dict__.clear()
            return result.unwrap()
    finally:
        # To guarantee that we never swallow a KeyboardInterrupt, we have to
        # check for pending ones once more after leaving the context manager:
        if ki_status.pending:
            # Implicitly chains with any exception from result.unwrap():
            raise KeyboardInterrupt

# 24 hours is arbitrary, but it avoids issues like people setting timeouts of
# 10**20 and then getting integer overflows in the underlying system calls.
_MAX_TIMEOUT = 24 * 60 * 60

def run_impl(runner, fn, args):
    runner.spawn_impl(runner.call_soon_task, (), type=TaskType.SYSTEM)
    try:
        runner.initial_task = runner.spawn_impl(fn, args)
    except BaseException as exc:
        async def initial_spawn_failed(e):
            raise e
        runner.initial_task = runner.spawn_impl(initial_spawn_failed, (exc,))

    while runner.tasks:
        if runner.runq or runner.waiting_for_idle:
            timeout = 0
        elif runner.deadlines:
            deadline, _ = runner.deadlines.keys()[0]
            timeout = runner.clock.deadline_to_sleep_time(deadline)
        else:
            timeout = _MAX_TIMEOUT
        timeout = min(max(0, timeout), _MAX_TIMEOUT)

        runner.io_manager.handle_io(timeout)

        now = runner.clock.current_time()
        while runner.deadlines:
            (deadline, _), task = runner.deadlines.peekitem(0)
            if deadline <= now:
                task._fire_expired_timeouts(now, TimeoutCancelled())
            else:
                break

        if not runner.runq:
            while runner.waiting_for_idle:
                runner.reschedule(runner.waiting_for_idle.pop())

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
        runner.runq.clear()
        runner.r.shuffle(batch)
        while batch:
            task = batch.pop()
            GLOBAL_RUN_CONTEXT.task = task
            runner.instrument("before_task_step", task)

            next_send = task._next_send
            task._next_send = None
            final_result = None
            try:
                msg = next_send.send(task.coro)
            except StopIteration as stop_iteration:
                final_result = Value(stop_iteration.value)
            except BaseException as task_exc:
                final_result = Error(task_exc)

            if final_result is not None:
                # We can't call this directly inside the except: blocks above,
                # because then the exceptions end up attaching themselves to
                # other exceptions as __context__ in unwanted ways.
                runner.task_finished(task, final_result)
            else:
                yield_fn, *args = msg
                if yield_fn is yield_briefly_no_cancel:
                    runner.reschedule(task)
                else:
                    assert yield_fn is yield_indefinitely
                    task._abort_func, = args
                    task._deliver_any_pending_cancel_to_blocked_task()

            runner.instrument("after_task_step", task)
            del GLOBAL_RUN_CONTEXT.task

    # If the initial task raised an exception then we let it chain into
    # the final result, but the unhandled exception part wins
    return Result.combine(runner.initial_task._task_result,
                          runner.unhandled_exception_result)

def current_task():
    return GLOBAL_RUN_CONTEXT.task

def current_deadline():
    return GLOBAL_RUN_CONTEXT.task._next_deadline()

@_hazmat
async def yield_if_cancelled():
    if current_task()._has_pending_cancel():
        await _core.yield_briefly()
        assert False  # pragma: no cover

_WRAPPER_TEMPLATE = """
def wrapper(*args, **kwargs):
    locals()[LOCALS_KEY_KEYBOARD_INTERRUPT_SAFE] = False
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
            ns = {"GLOBAL_RUN_CONTEXT": GLOBAL_RUN_CONTEXT,
                  "LOCALS_KEY_KEYBOARD_INTERRUPT_SAFE": LOCALS_KEY_KEYBOARD_INTERRUPT_SAFE}
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
