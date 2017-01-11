import signal

# runqueue is a regular deque
# primitives:
# - remove from runqueue (with cancel func)
# - add to runqueue
# - add I/O watch
# - add to runqueue while cancelling
# - get time
# - activate/deactivate cancel token
#
# tasks

# there's no reason to support send, really? I guess if you have lots of tiny
# messages that you want to generate at the last second or something really
# messy like that?

# I/O operations...:
# - read/write/close
# - accept/send (+ variants)/recv (+ variants)
# - shutdown
# - LockFileEx
# - gethostbyname
# - waitpid
# - wait for signal
# - inotify-like APIs
# - writeable (not readable)
#   -- and should be documented as a hint, since Windows and SSL don't
#      really support it
#
# https://msdn.microsoft.com/en-us/library/windows/desktop/aa365198(v=vs.85).aspx
# some are pretty obscure -- need an escape to call stuff like
# TransactNamedPipe, weirdo kqueue options, etc.

# writeable on windows:
# http://stackoverflow.com/a/28848834
# maybe this is usable? (Windows 8+ only though :-()
# https://msdn.microsoft.com/en-us/library/windows/desktop/ms741576(v=vs.85).aspx
# -> can't figure out how to hook events up to iocp :-(
# also of note:
# - to be usable with IOCP, you have to pass a special flag when *creating*
# socket or file objects, and this can affect the semantics of other
# operations on them.
#   - there's ReOpenFile, but it may not work in all cases:
#     https://msdn.microsoft.com/en-us/library/aa365497%28VS.85%29.aspx
#     https://stackoverflow.com/questions/2475713/is-it-possible-to-change-handle-that-has-been-opened-for-synchronous-i-o-to-be-o
#     DuplicateHandle does *not* work for this
#       https://blogs.msdn.microsoft.com/oldnewthing/20140711-00/?p=523
#       https://msdn.microsoft.com/en-us/library/windows/desktop/ms741565(v=vs.85).aspx
#   - stdin/stdout are a bit of a problem in this regard (e.g. IPython) -
#     console handle does not have the special flag set :-(
#   - it is at least possible to detect this, b/c when you try to associate
#     the handle with the IOCP then it will fail. can fall back on threads or
#     whatever at that point.
# - cancellation exists, but you still have to wait for the cancel to finish
# (and there's a race, so it might fail -- the operation might complete
# successfully even though you tried to cancel it)
# this means we can't depend on synchronously cancelling stuff.
# - if a file handle has the special overlapped flag set, then it doesn't have
# a file position, you can *only* do pread/pwrite
# -
# https://msdn.microsoft.com/en-us/library/windows/desktop/ms740087(v=vs.85).aspx
# says that after you cancel a socket operation, the only valid operation is
# to immediately close that socket. this isn't mentioned anywhere else though...

# let's also define a Stream type, make sure that sockets/pipes implement it,
# and implement SSL as a wrapper around it. This looks like it's actually
# pretty easy using the SSLObject / BIO stuff in modern Python.
# (or should we prefer a cryptography-based public API?)

# we might want to mask SIGINT while inside the runner proper, only unmask
# while executing coro code

# All *active* interrupt tokens are kept in an orderedlist inside the runner

# clock:
# - get current time
# - convert deadline into maximum sleep time

from collections import deque
from time import monotonic

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

import itertools
import sortedcontainers

class Cancelled(Exception):
    partial_result = None
    interrupt = None

class TaskCancelled(Cancelled):
    pass

class TimeoutCancelled(Cancelled):
    pass

_counter = itertools.count()

class Interrupt:
    def __init__(self, manager):
        self._error = None
        self._tasks = set()
        self._manager = manager
        self._deadline = None
        self._tiebreaker = next(_counter)

    def __repr__(self):
        s = "<Interrupt"
        if self._error is None:
            s += ", not fired"
        else:
            s += ", fired with error=" + repr(self._error)
        if self._deadline is not None:
            s += ", deadline={!r}".format(self._deadline)
        s += ">"
        return s

    @property
    def deadline(self):
        return self._deadline

    def set_deadline(self, deadline):
        if self._deadline is not None:
            self._manager.disable_timed_interrupt(self)
        self._deadline = deadline
        if self._deadline is not None:
            self._manager.enable_timed_interrupt(self)

    def __del__(self):
        assert not self._tasks
        if self._deadline is not None:
            # This method is safe to call here, because it doesn't touch the
            # weakref (which has already been cleared).
            self._manager.disable_timed_interrupt(self)

    async def _add_task(self, task):
        self._tasks.add(task)

    def _remove_task(self, task):
        self._tasks.remove(task)

    def fire(self, error):
        if not isinstance(error, CancelBase):
            raise ValueError("error must be a CancelBase instance")
        # XX FIXME: I guess we need to copy the exception when we raise it;
        # maybe we should attach our self only to the copy?
        error.interrupt = self
        self._error = error
        self.set_deadline(None)
        while self._tasks:
            task = self._tasks.pop()
            if task._interrupt_callback is not None:
                task._interrupt_callback(self)

    def fired(self):
        return self._error is not None

def _key(interrupt):
    return (interrupt._deadline, interrupt._tiebreaker)

class TimedInterruptManager:
    def __init__(self):
        self._interrupts = sortedcontainers.SortedDict()
        self._values = self._interrupts.values()

    def enable_timed_interrupt(self, interrupt):
        self._interrupts[_key(interrupt)] = weakref.ref(interrupt)

    def disable_timed_interrupt(self, interrupt):
        # This method is called from Interrupt.__del__, so it can't assume
        # that the weakref is valid. Fortunately it has no need to look at the
        # weakref.
        del self._interrupts[_key(interrupt)]

    def next_timeout(self):
        if self._interrupts:
            return self._values[0]._deadline
        else:
            return None

    def fire_older_than(self, now):
        while True:
            interrupt_ref = self._values[0]
            interrupt = interrupt_ref()
            if interrupt._deadline < now:
                # Implicitly removes interrupt from our data structures:
                interrupt.fire(TimeoutCancelled())
            else:
                break

    def close(self):
        # Break reference cycles
        while self._values:
            self._values[0]().set_deadline(None)
        # Make sure that any attempt to use this manager raises an
        # error. (E.g., b/c someone allocated an Interrupt object during one
        # call to run(), and then tried to use it on a second call.) This
        # should never happen, but if it does then it's better to fail fast.
        del self._interrupts, self._values


import abc
import attr

@attr.s(slots=True)
class Result(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def unwrap(self):
        pass

    @abc.abstractmethod
    def send(self, it):
        pass

    @attr.s(slots=True)
    class Value(Result):
        value = attr.ib()

        def unwrap(self):
            return self.value

        def send(self, it):
            return it.send(self.value)

    class Error(Result):
        error = attr.ib()

        def unwrap(self):
            raise self.error

        def send(self, it):
            return it.throw(self.error)

# old_result can be Value, Error, or None
def chain_error(old_result, new_exc):
    if type(old_result) is Result.Error:
        root = new_exc
        while root.__context__ is not None:
            root = root.__context__
        root.__context__ = self._exc
    return Result.Error(exc)

def result_from_call(fn, *args, **kwargs):
    try:
        return Result.Value(fn(*args, **kwargs))
    except BaseException as exc:
        return Result.Error(exc)

class Queue:
    async def put(self, obj):
        # ...
        pass

    def put_nowait(self, obj):
        # ...
        # raises if full
        # This is what tasks uses to report results

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

class WouldBlock(Exception):
    pass

class Task:
    def __init__(self, coro, result_qs=[]):
        self.coro = coro
        self._task_result = None
        self._next_send = Result.Value(None)
        self._result_qs = set(result_qs)
        self._interrupt_callback = None
        self.cancel_interrupt = Interrupt()
        self._cancel_stack = [self.cancel_interrupt]

    def cancel_nowait(self, exc=None):
        if exc is None:
            exc = TaskCancelled()
        self.cancel_interrupt.fire(exc)

    def add_result_q(self, result_q):
        if result_q in self._result_qs:
            raise ValueError("can't add same result queue twice")
        self._result_qs.add(result_q)
        if self._task_result is not None:
            result_q.put_nowait(self)

    def remove_result_q(self, result_q):
        self._result_qs.remove(result_q)

    def join(self):
        if self._task_result is None:
            q = Queue()
            self._result_qs.add(q)
            await q.get()
        return self._task_result

    def join_nowait(self):
        if self._task_result is None:
            raise WouldBlock()
        else:
            return self._task_result

class DispatchTable:
    def __init__(self):
        self._table = {}

    def implements(self, key):
        def wrap(fn):
            self._table[key] = fn
            return fn

    def call(self, key, *args, **kwargs):
        return self._table[key](*args, **kwargs)

    def keys(self):
        return self._table.keys()

# Block keyboard interrupt
if hasattr(signal, "pthread_sigmask"):
    @contextmanager
    def sigmask(self, how, mask):
        original = signal.pthread_sigmask(how, mask)
        try:
            yield original
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, original)
else:
    @contextmanager
    def sigmask(self, how, mask):
        yield []

import enum

SyncTrap = enum.Enum("SyncTrap", [
    "now",
    "new_interrupt",
    "reschedule",
])

def run(initial_async_callable, clock=None, profiler=None):
    if clock is None:
        clock = SystemClock()
    if profiler is None:
        profiler = NullProfiler()
    with closing(TimedInterruptManager()) as timed_interrupt_manager, \
         closing(profiler),                                           \
         sigmask(signal.SIG_BLOCK, signal.SIGINT) as original_sigmask:
        try:
            # The main reason this is split off into its own function is just
            # to get rid of this extra indentation.
            #
            # This currently assumes _run returns a Result and that we want to
            # do the same.
            return _run(initial_async_callable, clock, profiler,
                        timed_interrupt_manager, original_sigmask)
        except BaseException as exc:
            raise InternalError() from exc

def _run(initial_async_callable, clock, profiler,
         timed_interrupt_manager, original_sigmask):
    # Hide this giant function from pytest tracebacks
    __tracebackhide__ = True

    initial_task = Task(initial_async_callable())

    final_result = None

    tasks = set()
    tasks.add(initial_task)
    runq = deque()
    runq.append(initial_task)

    sync_traps = DispatchTable()

    @sync_traps.implements(SyncTrap.now)
    def _sync_trap_now(self):
        return clock.now()

    @sync_traps.implements(SyncTrap.new_interrupt)
    def _sync_trap_new_interrupt(self):
        return Interrupt(timed_interrupt_manager)

    @sync_traps.implements(SyncTrap.reschedule)
    def _sync_trap_reschedule(self, task):
        task.


    assert set(sync_traps.keys()) == set(SyncTrap)


    # Shut down logic:
    # - if any task crashes, then we cancel all non-daemon tasks, and ensure
    #   that any new tasks which are spawned are insta-cancelled
    # - once the main

    while True:
        # Process all runnable tasks, but wait for the next iteration
        # before processing tasks that become runnable now. This avoids
        # various starvation issues by ensuring that there's never an
        # unbounded delay between successive checks for I/O.
        for _ in range(len(self._runq)):
            task = self._runq.popleft()
            profiler.before_task_step(task)
            while True:
                try:
                    with sigmask(signal.SIG_SETMASK, original_mask):
                        msg = task._next_send.send(task.coro)
                except StopIteration as stop_iteration:
                    # Task finished, clean up.
                    self._tasks.remove(task)
                    # XX
                    task._task_result = Result.Value(stop_iteration.value)
                    if task is initial_task:
                        # XX
                    if task._result_q is not None:
                        try:
                            task._result_q.put_nowait(task)
                        except Exception as put_error:
                            # XX crash logic
                            pass
                except BaseException as task_crash_error:
                    task._task_result = Error(task_crash_error)
                    if task._result_q is not None:
                        try:
                            task._result_q.put_nowait(task)
                        except Exception as put_error:
                            # XX crash logic
                    else:
                        # XX crash logic
                if type(msg.trap) is SyncTrap:
                    task._next_send = result_from_call(
                        sync_traps.call,
                        msg.trap, *msg.args, **msg.kwargs)
                else:
                    # blocking trap
                    profiler.after_task_step(task)
                    task._next_send = None
                    # XX process it
                    break
