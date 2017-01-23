nothing to see here

..
   Trio – async I/O for humans
   ===========================

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

   *Does it work on my machine?* Trio and its dependencies are all
   pure Python, except that on Windows it needs cffi. So if you have
   some kind of Python 3.5+ on any popular-ish platform, then it
   should work. Linux, MacOS, and Windows are all fully supported,
   *BSD probably works too though isn't tested, and the last time I
   checked a PyPy3 nightly build it worked fine.

   *I want to know more!* Check out the `documentation
   <https://trio.readthedocs.io>`.

   *I want to try it!* Awesome! ``pip install trio`` and check out
   `our examples XX`

   *I want to help!* You're the best! Check out our  <github issues>
   discussion, tests, docs, use it and let us know how it goes

   *I want to make sure my company's lawyers won't get angry at me!*
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
   - should tasks be context managers?

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

   - also according to the docs on Windows, with overlapped I/o you can
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
