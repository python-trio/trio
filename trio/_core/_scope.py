from math import inf

import attr

# On cancellation, we throw *one* exception into *the one task* we're
# associated with.
#
# Rule for user code: never catch a cancellation exception! Always let it
# propagate (or replace it with a real error if there's an error cancelling).
#
# when we hit scope __exit__, if we have an exception (including cancelled)
# cancel all child scopes
# then wait for all child scopes
# and aggregate exceptions. cancellations triggered by *this* scope being
# cancelled are dropped. exceptions propagate. cancellations from somewhere
# else + error = error. Though... errors can be handled, cancellation
# can't. Hmm. CancelledWithErrorPayload?
#
# of course it's necessarily the case that cancellation exceptions can be
# wiped out by regular errors, just something like an __exit__/finally block
# with a typo in it will do it.
# and KeyboardInterrupt has the same problem but people seem to survive...
#
# some way to recover after handling an error that might have stomped on a
# cancellation?
#
# if current_cancelled():
#     ...
#
# # or, re-raises the correctly annotated Cancelled if any:
# reraise_any_pending_cancel()
#
#
# ...or maybe AggregatedError just keeps Cancelled in it (and stripped out en
# passant at appropriate moments) (mild issue: so does AggregatedError inherit
# from Exception or not? I guess we can have AggregatedErrorCancelled and
# AggregatedError and switch back and forth as necessary? maybe a
# BaseAggregatedError in there as well?)
#
# ...once we have aggregated errors then that also solves the problem of
# people trying to inject multiple errors at once...

# class BaseMultiError(BaseException):
#     pass

# class MultiErrorCancelled(BaseMultiError, Cancelled):
#     pass

# class MultiError(BaseMultiError, Exception):
#     pass

# and once we have multierror then maybe that's the way to handle nested
# cancellation as well?

# so maybe:
# - MultiError has generic code for aggregating/disaggregating exceptions
# - task has an inject_exception method, that knows about how to call abort,
#   etc.
# - scope just injects exceptions when a child crashes or a timeout expires or
#   someone calls cancel()

# would it make more sense for fail_after to inject TooSlowError from the
# start instead of messing about with cancelling? -- no, probably not, because
# it could get injected inside of another fail_after and confuse everyone.
#
# should we even wrap child exceptions by default? Maybe it's better to reveal
# the real exception (e.g. KeyboardInterrupt!) and only create a new type if
# we have to aggregate multiple exceptions?
#
# wrapping scope around task: maybe code like
#
# async def task_helper(task_scope, fn, args):
#     async with task_scope:
#         await fn(*args)
#
# so the scope object is available outside the task before it starts?
#
# though need to be careful then that entering the task_scope is not a
# cancellation point, b/c that would allow tasks to be pre-cancelled before
# they even start, which is confusing.

# somehow we need to tell whether we actually delivered a cancellation
# exception, because if it was still pending when we exited the scope, then it
# doesn't really count. even if it was finally delivered to us inside the
# scope exit.
#
# new idea: keep the exc we injected, and at scope exit attempt to "uninject"
# it. .....but this is a mess if we're cancelled multiple times. do we still
# need to support multiple cancellation?
#
# used for:
# - delivering KeyboardInterrupt, but I think we can do that otherwise
# - used when crashing, or in the new world order, when parent scope is
#   exiting with exception
# - kind of messy if we have multiple cancellation types
#
# so could stick with only 1 cancellation type and make cancellation a
# one-off?
#
# ...what if we just don't provide a flag at all? like, if you want to know if
# the request completed, set a flag or something?
#
# async with new_scope(deadline=...) as scope:
#     ...
# or timeout=...
#
# for candidate_host in host_list:
#     with cancel_scope(timeout=...):
#         return await make_connection(candidate_host)
#
# fail_after is pretty important though :-( and we definitely cannot have it
# inject the final exception type directly or composition gets all borked.
# unless we say that you can *never* catch a TooSlowError, but... c'mon.
#
# okay let's put this aside for now though. For now, there is no signal
# whether a scope was cancelled or not.
#
#
# is it an error if a scope was cancelled to reach __exit__ without an
# exception set (or pending)?
#
#
# I guess a common bug would be for code that's been set up as a failure
# isolation boundary, like a restarting supervisor, to miss that it's been
# canceled b/c some code accidentally converted a Cancelled into some other
# kind of error?
# actually this should be OK, because the Cancelled just goes into the
# supervisor, *not* the child tasks -- there's some separation there.
#
#
# convenience methods for catching/rethrowing parts of MultiErrors?
#
#
# you know maybe it would be better if the ability to spawn children was more
# tightly controlled. it really doesn't make sense to *nest* supervisors, and
# there's all kinds of horribleness likely if, like, you have a supervisor
# that's trying to monitor children explicitly with a queue, but then a
# higher-up supervisor *doesn't* have a queue registered so the lower-down
# supervisor is getting random ChildCrashed exceptions thrown into it.
#
# So like maybe you have to explictly create a supervisor context if you want
# to spawn at all?
#
# give unboundedqueue a push_back_all_nowait method to push back entries onto
# the queue that we don't want to process now
# anything in the queue when we get back to __exit__ will be processed there
#
# if you want to process the queue, cool, otherwise, just spawn your initial
# children and then park in __exit__ to get its default handling.

# 2-way proxy:
async with supervisor() as s:
    await s.spawn(copy_all, a, b)
    await s.spawn(copy_all, b, a)

async def race(candidates):
    async with task_group() as tg:
        for candidate in candidates:
            await tg.spawn(*candidate)
        batch = await tg.monitor.get_all()
        tg.monitor.unget_all_nowait(batch[1:])
        tg.cancel_all()
        return batch[0].unwrap()

# if any raise, cancels the remainder and raises an aggregate exception
async def concurrent_map(fn, iterable):
    async with task_group() as tg:
        tasks = {}
        for i, obj in enumerate(iterable):
            tasks[i] = await tg.spawn(fn, obj)
        results = [None] * len(tasks)
        async for task_batch in tg.monitor:
            for task in task_batch:
                results[tasks[task]] = task.result.unwrap()
    return results

# Handles cancellation by cancelling everything and then raising an aggregate
# error; otherwise returns a list of Results.
# Hmm, this is kinda broken in that if we are cancelled or otherwise error out
# we don't want an aggregate error, we want to discard child task errors.
async def concurrent_map_results(fn, iterable):
    async with task_group() as tg:
        try:
            tasks = {}
            for i, obj in enumerate(iterable):
                tasks[i] = await tg.spawn(fn, obj)
            results = [None] * len(tasks)
            async for task_batch in tg.monitor:
                for task in task_batch:
                    results[tasks[task]] = task.result
        except:
            tg.cancel_all()
            # maybe?
            await tg.wait()
            # or?
            while tg.tasks:
                await tg.monitor.get_all()
            raise
    return results

# maybe Task.add_monitor should just refuse to accept any object except an
# actual UnboundedQueue? and then a put_nowait error could be an
# InternalError?

# let's have put_all_nowait instead of unget_all_nowait, just fits better and
# just as good for all the uses so far

# XX make sure that UnboundedQueue only wakes on transitions from
# empty->!empty

# XX should regular queues default to capacity=1? ...should they even
# *support* capacity >1?

# XX tasks have a private reference to containing nursery, nursery has a
# private reference to containing task (I guess, privacy here doesn't matter
# too much), and tasks have a public @property pointing to parent task, to
# prevent nursery references leaking out where they weren't passed.

# ...if nursery is the only way to spawn, and nursery creation requires await,
# so you can only spawn if passed async OR passed a reference to a nursery,
# then... does spawn actually need to be async? esp. since the ability to
# *create* a nursery doesn't actually let you violate causality! only being
# passed a reference to someone else's nursery lets you do that.

# start_* convention -- if you want to run it synchronously, do
# async with make_nursery() as nursery:
#     task = await start_foo(nursery)
# return task.result.unwrap()
# we might even want to wrap this idiom up in a convenience function

# for our server helper, it's a start_ function
# maybe it takes listener_nursery, connection_nursery arguments, to let you
# set up the graceful shutdown thing? though draining is still a problem.

# XX I suspect threading.RLock is not signal-safe on pypy.
# (it's definitely not on pypy2)
# how about deque?

# for call_soon locking, note that it's still correct if we write the trio
# thread's part as:
#   closing = True
#   with lock:
#       pass

# nurseries inside async generators are... odd. they *do* allow you to violate
# causality in the sense that the generator could be doing stuff while
# appearing to be yielded. I guess it still works out so long as the generator
# does eventually complete? if you leak this generator though then ugh what a
# mess. worst case we leak tasks -- the root task has exited, but there are
# still incomplete tasks floating around. not sure what we should do in that
# case. besides whine mightily.

# algorithm for WFQ ParkingLot:
# if there are multiple tasks that are eligible to run immediately, then we
# want to wake the one that's been waiting longest (FIFO rule)
# otherwise, we want to wake the task that will be eligible to run first
# for each waiter, we know its entry time and its vtime
# we keep two data structures: one sorted by vtime, and one by entry
# time. Any given task is listed on *one* of these, not both! the vtime
# collection holds tasks that are not eligible to run yet (vtime in the
# future); the FIFO collection holds tasks that are eligible to run
# immediately (vtime in the past).
# to wake 1 task:
# - get the current vtime on the vclock
# - look at the set of tasks sorted by vtime, and for all the ones whose vtime
#   is older than the current vtime, move them to the FIFO queue
# - pop from the FIFO queue
# - unless it's empty, in which case pop from the vtime queue
# this is something like amortized O(N log N) to queue/dequeue N tasks.
#
# HWFQ is... a much worse mess though, b/c a task could be eligible to run now
# but become ineligible before being scheduled :-(

# I looked at h2, and yeah, we definitely need to make stream have aclose()
# instead of close(). Sigh.
# ...if aclose is a cancellation point, does it need special cancellation
# semantics, like the mess around POSIX close? I'm leaning towards, it's
# implemented as
# async def aclose(self):
#     self.close()
#     await yield_briefly()
#
# and on that note I guess we should @ki_protection_enabled all our __(a)exit__
# implementations...! include @acontextmanager -- it's not enough to protect
# the wrapped function. (In fact, maybe we need to do both? not sure what the
# call-stack looks like for a re-entered generator... and ki_protection for
# async generators is a bit of a mess, ugh. maybe ki_protection needs to use
# inspect to check for generator/asyncgenerator and in that case do the local
# injection thing. or maybe yield from.)

async with children() as c:
    c.spawn()

# nursery
# nanny
# daycare
# babysitter
# créche, that would annoy everyone :-)
# governess - no.

# new_nursery? make_nursery?
# manage_nursery? open_nursery?

class TaskGroup:
    tasks = attr.ib(default=attr.Factory(set))
    monitor = attr.ib(default=attr.Factory(_core.UnboundedQueue))
    closing = attr.ib(default=False)

    def _task_finished(self, task):
        self.tasks.remove(task)
        self.monitor.put_nowait(task)

    # XX split the closing=True from the cancel_all? start_shutdown?
    # not start_, if that's the convention we use for task starters.

    # alternative would be that if cancel_all was called then we allow new
    # ones but cancel them as they arrive.
    # this might be more convenient for call_soon(spawn=True), actually...

    # what is the exit criterion? should we stop accepting new spawns when we
    # enter __aexit__?

    def cancel_all(self):
        if not self.closing:
            self.closing = True
            for task in self.tasks:
                task.cancel()

    async def spawn(self, task, *args):
        if self.closing:
            raise RuntimeError(XX)
        task = _internal_spawn(self, task, args)
        self.tasks.add(task)

    async def __aexit__(self, _, value, _):
        exceptions = []
        if value is not None:
            exceptions.append(value)
        while self.tasks:
            if exceptions:
                self.cancel_all()
            batch = await self.monitor.get_all()
            for task in batch:
                if type(task.result) is Error:
                    exceptions.append(task.result.error)
        self.closing = True
        if exceptions:
            XX raise aggregate

    def __del__(self):
        assert not self.tasks

@attr.s(slots=True, cmp=False, hash=False)
class Scope:
    parent = attr.ib()    # another scope, or None if this is the root scope
    _deadline = attr.ib()  # float, maybe inf
    task = attr.ib()      # ??
    # set of task scopes
    _children = attr.ib(default=attr.Factory(set))
    _cancelled = attr.ib(default=False)
    _monitor = attr.ib(default=None)
    living = attr.ib(default=True)


    def _parent_chain(self):
        while self is not None:
            yield self
            self = self.parent

    @property
    def effective_deadline(self):
        deadline = min(scope._deadline for scope in self._parent_chain())

    @property
    def deadline(self):
        XX

    @property.setter
    def deadline(self):
        XX

    async def spawn(self, fn, *args):
        XX

    def cancel(self, exc):
        if isinstance(exc, type) and issubclass(exc, BaseException):
            exc = exc()
        if not isinstance(exc, _core.Cancelled):
            raise TypeError(
                "expected instance of Cancelled, not {}".format(exc))
        if self._cancelled:
            return
        self._cancelled = True
        exc._scope = self
        self.deadline = inf
        self.task._inject_exception(exc)

    def _child_finished(self, child_scope):
        XX

# Shouldn't be a method on scope, because the only form we want to allow is a
# task monitoring its own innermost scope?
# or maybe we should allow it to monitor outer scopes within the same
# task. but definitely not other tasks.
@contextmanager
def child_monitor(self):
    XX

@acontextmanager
@ki_protection_enabled
async def activate_scope(scope):
    # push onto task stack so it can call effective_deadline and so spawn()
    # can find us
    if task_scope:
        add to parent table
    push onto task stack
    try:
        yield scope
    finally:
        # exiting scope
        pop from task stack
        remove from deadlines table
        wait for children
        exceptions = []
        _, exc_context, _ = sys.exc_info()
        if exc_context is not None:
            exceptions.append(exc_context)
        # XX this won't do because we can't filter out cancellations from
        # child task scope. Or maybe that should be done by the child, with
        # some special option to override it in the few cases where we want to
        # allow those exceptions to propagate?
        cancelled_children = False
        while self.children:
            if exceptions and not cancelled_children:
                for child in self.children:
                    child.cancel()
                cancelled_children = True
            try:
                await next(iter(self.children)).wait()
            except BaseException as exc:
                exceptions.add(exc)
        filter out cancelled exceptions
        if task_scope:
            notify parent of completion
        raise remainder

def new_scope():
    XX create new scope
    return activate_scope(XX)
