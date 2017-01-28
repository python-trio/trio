nothing to see here

..
   Trio – async I/O for humans and snake people
   ============================================

   Trio is an `async/await-native
   <https://vorpus.org/blog/some-thoughts-on-asynchronous-api-design-in-a-post-asyncawait-world/>`__
   I/O library for Python 3.5+ (including nightly builds of PyPy3),
   with full support for Linux, MacOS, and Windows.

   how to make it *easy and fun* to write *safe, correct, and
   performant* asynchronous code in Python.  Async programming has a
   reputation for melting people's brains. We're trying to fix that.

   current state experimental and unstable but goal is to

   Trio represents one possible vision of the future of asynchronous
   I/O in Python, but it's not the only such vision. If you're
   interested in trio, then you should check out `asyncio
   <https://docs.python.org/3/library/asyncio.html>`__ and `curio
   <https://github.com/dabeaz/curio>`__ too.

   So... where to next?

   *Does it work on my machine?* We fully support Linux, MacOS, and
   Windows, running Python 3.5+ (including PyPy 3.5 nightly builds).
   Trio and its dependencies are all pure Python, except that on
   Windows it needs cffi. *BSD might work too though isn't tested.

   *I want to know more!* Check out the `documentation
   <https://trio.readthedocs.io>`.

   *I want to try it!* Awesome! ``pip install trio`` and check out
   `our examples XX`. And if you use it for anything more than toy
   experiments, then you should <XX subscribe to this issue>.

   *I want to help!* You're the best! Check out our  <github issues>
   discussion, tests, docs, use it and let us know how it goes XX

   *I just love thinking about !* You might enjoy our <XX reading list>

   *Are my company's lawyers going to get angry at me?*
   No worries, trio is permissively licensed under your choice of MIT
   or Apache 2. See `LICENSE
   <https://github.com/njsmith/trio/blob/master/LICENSE>`__ for
   details.


   emphasis on usability: goal is to help you write programs that are
   safe, correct, low latency, high throughput
   (in that order)

   is it fast? it's not slow; for real optimization though going to wait
   until we have real programs, b/c we'd rather not get into a fight over
   who has the fastest echo server in the west. (rule: optimizations must
   either demonstrate appreciable speedups on realistic (ideally real)
   applications *or* demonstrate appreciable speedups on
   microbenchmarks + be ~neutral WRT to code maintainability.)

   minimal (TOOWTDI), layered design
   -> as a way to minimize the tension between stability and experimentation
   (e.g., there is only one *built-in* synchronization primitive, the
   ParkingLot; we provide the standard set of primitives like locks,
   queues, etc. built on top of it, but you can pretty easily write your
   own if you need them.)

   make it as easy as possible to reason about concurrency and
   cancellation
   documented which points are cancellation points, etc.
   clear principles for which functions are async and which aren't

   exceptions cannot pass silently

   goals that we don't meet yet, but want to:
   rigorous test suite
   cross-platform (and only *one* implementation per platform)
   stable


   Implemented:
   - Core loop functionality (tasks, timeouts, cancellation, etc.)
   - Thread/signal-safe assignment of work to the trio thread
   - Listening for signals
   - run_in_worker_thread
   - {run,await}_in_trio_thread (from outside threads)

   Needs work:
   - KeyboardInterrupt handling
   - Synchronization primitives (Event, Queue, Semaphore, etc.)
   - IDNA (someone help me please)

   Needs written:
   - socket module:
     - sendfile
   - some sort of supervision story (+ probably want to change task API
     in the process)
   - docs
   - subprocesses
   - worker process pool
   - SSL


   design/API principles:

   functions that take thunks (run, spawn, call_soon_threadsafe,
   run_in_thread, ...) all follow the pattern

   def caller(thunk, *args_for_thunk, *, **kwargs_for_caller)

   "notify"-style operations are sync-colored

   potentially-blocking operations always check for cancellation first,
   and always invoke the scheduler

   whenever possible, have a statistics() method that returns an
   immutable object with attributes that provide some useful stats --
   e.g. for a lock, number of waiters


   spawn is special: it's the only async-colored primitive that executes
   synchronously. (it's unconditionally synchronous.)
   all other async-colored primitives are unconditionally cancellation
   points and unconditionally invoke the scheduler.
   for non-primitives,
   => async means: at least sometimes invokes concurrency, suspension,
   cancellation
   admittedly this is a conceptual distinction rather than a strict
   technical one, e.g. we could set up a "spawn server" and then send
   spawn requests to it using synchronous calls to put_nowait, but we
   conjecture that it's a useful conceptual distinction.
   and in fact threads can do this!


   next:
   - if one cancel steps on another, we should chain them

     we still have the lurking issue that chaining does *hide* the
     underlying exception
     it's fine for sequential code where the second exception actually
     does arise from the path handling the first, but not so clear
     when aggregating from multiple parallel contexts...

   - I use .join() when I want .wait(). So split these up.

     async with supervisor() as s:
         await start_foo(s.spawn, ...)
         await start_bar(s.spawn, ...)
         async for task in s:
             ...

     - if we leave the block, it cancels all remaining tasks, waits
       for them to finish, and re-raises any exceptions. So this takes
       care of parent-can't-die-before-child, and also guarantees they
       all get reaped.

     but the thing coming out of the for loop is still the task
     object, easy to not check it for errors.

     *how do we make sure errors go somewhere?*

     Task.unwrap(); if this isn't called then re-raise at the end?

     send ChildExitCancelled to nominated supervisor when the child
     exits, unless they've set up a queue to receive it instead and
     trust that if they did that then they'll handle it properly?
     ParentExitCancelled
     it would help if there were better ways to aggregate errors...

     cancellation by itself is an inadequate way to propagate
     exceptions because if a task exits while the cancellation is
     pending then the cancellation just goes away

     a downside to the current blow-up-the-world fallback is that if
     you *do* want a guarantee that the world won't blow up it's hard
     to implement that.

     use cases:

       jongleur: supervise a large collection of tasks that come and
         go, propagate any exceptions, support drain and killall

       two-way proxy: spawn two children, wait for them both to
         finish, propagate errors both directions

       concurrent IO: start a bunch of request.get() calls, gather the
         results as they come in

     strawman:

       - parents cannot die before children. if they try, then
         children get cancelled and the parent waits on them.
       - by default:
         - if a child dies with an exception, raise an exception in the
           parent
         - if a child exits normally, that's fine, don't hassle the parent
       - if parent opts in to notifications:
         - they just get told about child exit (regardless of state)

            with child_monitor() as m:
               async for task in m:
                   ...

            any task that doesn't get pulled out counts as unreaped?
            (should be batched, probably just use an UnboundedQueue,
            and when the monitor __exit__'s pull out anything
            remaining in the queue. and nice, the child_monitor pun
            works with the other *_monitor context managers)
            ...maybe the queue stops iteration when there are no more
            children? need some extension to UnboundedQueue for that.
            (what's up with task_done() and all that anyway -- can't
            we close() and then join()?)
        - when spawning, can specify a parent; default is current task

     in this setup, this code is actually correct...

       tasks = [await _core.spawn(fn) for fn in fns]
       for task in tasks:
           await task.wait()

     if one of them crashes, then the current task.wait() will get
     cancelled

     hmm, but this is not a normal cancel -- it should propagate!
     (and as noted above, if not delivered that should be noted)
     maybe distinguish between cancel and inject exceptions?
     AsyncError vs Cancelled?

     maybe tasks are the wrong scope for this though. Maybe it should
     be a, well... "scope" first-class concept, so

       with move_on_after(10):
           await spawn(...)

     automatically waits on the child *when exiting the
     move_on_after*?

     ...should cancelling the scope automatically cancel the tasks
     inside it? when the timeout fires should the child tasks get
     timeout exceptions?
       (if so then scope.raised becomes ambiguous)

       current_scope()
       spawn is a method on scope
       every task introduces an implicit scope
       scope.effective_deadline()

     scope tree
       only operations that create scopes are task spawn and context
       managers
       and these are also the only operations that associate a scope
       to a task
       the scope created by spawning a new task can have any arbitrary
       open scope as its parent, but context manager scopes can only
       be parented by the current top of the current task's scope
       stack

       so this means that the task tree is a strict coarsening of the
       scope tree

     a scope has:
     - deadline
     - exactly 1 parent scope (if self is living, parent must be living)
     - 0 or more child task scopes (all living)
     - 0 or 1 child within-task scopes (all living)

     state: live, dead, raised
       I guess "can recover and retry" is dead + raised + parent live?

     ...do we cancel the children if we reach the end of the scope, or
     just wait on them? maybe have to cancel...

     operations:
     - cancel
     - adjust timeout
     - spawn new task
     - push new within-task scope
     - get effective timeout

     control-C is similar to cancelling the root scope? (except it
     propagates out of run())
       I guess we do kind of want cancels to propagate sometimes --
       if an await_in_trio_thread gets cancelled we should tell the
       caller. and if the main task gets cancelled we should tell the
       caller.

       maybe the intuition is that it propagates out of the task, and
       gets swallowed by the context manager? ...well, this doesn't
       make much sense, because the distinction here is between cancel
       directed at the task scope versus cancel in one of the higher
       scopes, and the distinction above is about if there's someone
       outside the trio system telling them what happened.

       I guess it's the job of the code receiving the task completion
       notification to decide whether it thinks a cancelled exception
       is worth passing on.

     I'm not 100% clear on how to handle multiple cancels, or parent
     cancellation...

     "injected error":
       - control-C, fine
       - when a child task crashes and the parent is not monitoring
         this is like a cancellation in terms of its delivery
         semantics, except...

         - if there is, say, a cancellation + two crashed tasks
           pending, what do we do?

         for merging task crashes, I guess something like a
         ChildrenCrashedError that has *both* a list of all the
         exceptions + a __context__ chain linking them together so
         they all get printed? (or would it be __cause__ for the first
         and then __context__ after?)
         and an original_context for what the context would have been
         if not for this mess? hmm. I guess there isn't one, actually
         -- from a quick check, when you throw an exception into a
         sleeping coroutine, it *doesn't* get annotated with the
         coroutines exc_info context. I can't see any way to get the
         coroutine's exc_info either.

         for cancellation + crash, I guess we can apply the
         cancellation, and then the crash will stick around to appear
         during the scope cleanup?

     who parents call_soon(spawn=True) tasks? a few plausible
     options... dedicated system init task; the task specified when
     calling current_call_soon_thread_and_signal_safe; ...
       (might want to split into current_{call,spawn}_soon_... if
       gaining arguments that are only relevant to spawn=True version)

   - service registry? add a daemonic-ish task, maybe with a way to
     request a reference to it?

     maybe for waitpid support?

   - does yield_if_cancelled need to check the deadline before
     deciding whether to yield? could we get in a situation where a
     deadline never fires b/c we aren't yielding to the IO loop?
     though... actually this is a more general problem, because even
     in a pure model where we always await wait_socket_readable()
     before attempting the call (for example), then the readability
     success + rescheduling will happen before the timeout check!
     but then at least b/c we did yield the timeout will be marked as
     pending and delivered the next time -- the problem with
     yield_if_cancelled is that it may not yield. though... it is then
     paired with a yield_briefly_no_cancel, which I think is
     enough to arm the cancel, even if not deliver it? So maybe it's
     OK after all.

   - Maybe ParkingLot should return a ticket when unparking a task,
     that lets it repark and resume its place in line.

     ticket = None
     while not self._data:
         (ticket, value) = await self._lot.park(ticket=ticket)

     ...or maybe we should modify our uses of ParkingLot so that the
     waking task can't have its resource stolen out from under it?
     (strategy 1: hand off the lock directly to the woken task instead
     of releasing it and letting the waking task re-acquire
     it. strategy 2: get, get_nowait, acquire, etc., first check for
     whether there are tasks parked and if so they automatically
     park instead of stealing the resource.)

     maybe ParkingLot should have some sort of flag/counter, where
     parking consumes this, and you always park? so mutex unlock ->
     let one task through the gate. (maybe now, maybe later.) put 3
     items into queue -> let three tasks through the gate. I guess
     states are gate open, gate closed, N-tickets-available? this
     still doesn't handle all cases, like a queue with both get and
     get_all, where (a) if you have get, get, get_all, get in the
     wakequeue, and 4 items arrive, how do you know to wake just 3?,
     (b) even if you do wake just just 3, what happens if the get_all
     task runs first?

     I guess tasks could declare how many tickets they needed on
     entry. (get_all consumes: 1-infinity.) But that still
     doesn't solve the scheduling nondeterminism issue. Of course
     ParkingLot gets to be arbitrarily tightly integrated with the
     scheduler. Or we could tell tasks how many tickets they got?

   - XX add test for UnboundedQueue schedules properly (only wakes 1
     task if 2 puts)

   - if we eventually get a model where we're comfortable about
     crashes propagating everywhere in a nice way, then we might want
     to switch to a model where control-C just injects KI immediately
     if possible, and otherwise at the next switch to an unprotected
     task, and leave it at that.

     this would need to be the type of injected exception that
     propagates out of the task, though. (though if we're just
     brutally injecting it as the result of a yield, instead of going
     through the cancellation machinery, then I guess that wouldn't
     come up anyway!)

     problem: what to do if all tasks are blocked and loop is just
     sitting in the IOManager? need to pick one to abort, I guess...?
     it would suck if the one we picked to abort was uncancellable
     though. (maybe run_in_worker_thread should use
     yield_indefinitely_no_cancel, or at least a well-known lambda:
     FAILED callback so we can recognize unabortable tasks and pick a
     different one?)

   - factor call_soon machinery off into its own object

   - unifying the task cancel and timeout cancel systems

     would it be easier if we wrap tasks in a little async function
     that sets up the magic local (or not), and also puts a
     move_on_at(inf) wrapper around them?

     [showstopper: if we literally use move_on_at, it becomes
     impossible to cancel a task until after it's executed for a step
     and the move_on_at has had a chance to run and pass out the
     cancel handle]

     maybe expose the deadline as a Task.deadline property

     and make it possible to fire an arbitrary cancellation exception
     to cancel a chunk of work, via the CancelStatus object?

     this could also be used to *guarantee* that a task can't exit
     without waiting on its children

   - tasks from new lineages (the initial task, the call_soon task)
     treated in uniform way? if we crash before starting the initial
     task (ouch but can happen with instruments) then should cancel it
     immediately I guess. Or is it better to special case this and not
     even start?

   - join returning result is actually pretty bad because it
     encourages

        await task.join()

     to wait for a task that "can't fail"... but if it does then this
     silently discards the exception :-( :-(

     and we really can't make join() just raise the raw exception,
     because that can trivially get mixed up with cancellation
     exceptions

     curio's approach is an option, but kinda awkward :-/

     maybe:
     - join_nowait() -> .result, so there's no WouldBlock to confuse
       things, instead check .result is None before trying to unwrap
       it? (or don't)
     - join() -> wait(), which doesn't return anything and doesn't
       count as catching errors
     - explicit monitoring API is the only thing that counts as
       catching errors

   - according to the docs on Windows, with overlapped I/o you can
     still get WSAEWOULDBLOCK ("too many outstanding overlapped
     requests"). No-one on the internet seems to have any idea when
     this actually occurs or why. Twisted has a FIXME b/c they don't
     handle it, just propagate the error out.

   - not returning KeyboardInterrupt from run() is pretty annoying
     when running pytest

     of course, the naive thing of passing through keyboardinterrupt
     doesn't even work that well, since we'll end up with a bunch of
     Cancelled crashes

     maybe we should get more serious about KeyboardInterrupt. make a
     version that's a subclass of Cancelled, and if we detect a KI
     then raise it immediately in the current tasks and also inject it
     into *all* tasks as a cancellation.

     how to aggregate at the top-level, though? if everything exited
     with keyboardinterrupt or success, then cool, reasonable to make
     our final exception a keyboardinterrupt instead of an
     UnhandledExceptionError. if some raised new errors...?


     so:
     - when control-C is hit, raise inside the currently executing
       code (if not protected)
     - and also raise inside all regular tasks
       - possibly: raise at the next schedule point *even if* not
         otherwise cancellable then *if* they aren't protected against
         control-C. This might cause us to lose the result of the
         operation that got blown away (which is why cancellation
         can't normally happen here), but that's what control-C is
         like in general, so...
       - for protected code we need to go through the cancellation
         machinery
         - so it helps if the cancellation machinery allows us to send
           in an exception repeatedly!

     when tasks exit with a cancellation, it should be like there's a
     with move_on_after: wrapped around the whole thing, that swallows
     the exception if its the one we injected. the general rule with
     cancellations is to let them propagate. BUT for this it will help
     if there's a supervisor who notices and freaks out about
     "regular" death too...? well, and we need to be able to
     distinguish between unexpected exceptions, return None, and
     cancelled, probably?

     in general, there is *no* guarantee in trio that just because
     you've been cancelled once, you won't be cancelled
     again... because e.g. an outer timeout can fire while you're
     unwinding from an inner timeout.

   - kqueue power interface needs another pass + tests

   - possible improved robustness ("quality of implementation") ideas:
     - if an abort callback fails, discard that task but clean up the
       others (instead of discarding all)
     - if a clock raises an error... not much we can do about that.

   - trio
     http://infolab.stanford.edu/trio/ -- dead for a ~decade
     http://inamidst.com/sw/trio/ -- dead for a ~decade


   3.6 advantages:
   - no __aiter__ mess
   - async generators
   - no need to check for AbstractContextManager
   - f strings
   disadvantages:
   - not in debian at all yet; 3.6-final not in any ubuntu until 17.04

Code of conduct
---------------

Contributors are requested to follow our `code of conduct
<https://github.com/njsmith/trio/blob/master/CODE_OF_CONDUCT.md>`__ in
all project spaces.
