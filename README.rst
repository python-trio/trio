nothing to see here

..
   .. image:: https://readthedocs.org/projects/trio/badge/?version=latest
      :target: http://trio.readthedocs.io/en/latest/?badge=latest
      :alt: Documentation Status

   .. image:: https://travis-ci.org/njsmith/trio.svg?branch=master
      :target: https://travis-ci.org/njsmith/trio
      :alt: Automated test status (Linux and MacOS)

   .. image:: https://ci.appveyor.com/api/projects/status/af4eyed8o8tc3t0r/branch/master?svg=true
      :target: https://ci.appveyor.com/project/njsmith/trio/history
      :alt: Automated test status (Windows)

   .. image:: https://codecov.io/gh/njsmith/trio/branch/master/graph/badge.svg
      :target: https://codecov.io/gh/njsmith/trio
      :alt: Test coverage

..
   Trio – async I/O for humans and snake people
   ============================================

   *P.S. your API is a user interface – Kenneth Reitz*

   Trio is an experimental attempt to produce a production-quality,
   `permissively licensed
   <https://github.com/njsmith/trio/blob/master/LICENSE>`__,
   async/await-native I/O library for Python, with an emphasis on
   **usability** and **correctness** – we want to make it *easy* to
   get things *right*.

   Traditionally, async programming is quite challenging, with many
   subtle edge cases that are easy to get wrong. The addition of
   `asyncio <https://docs.python.org/3/library/asyncio.html>`__ to the
   standard library was a huge advance, but things have continued to
   move forward since then, and ironically, asyncio suffers from
   backwards-compatibility constraints that make it difficult for it
   to take full advantage of the new language features that it
   motivated. The resulting system can be `confusing
   <http://lucumr.pocoo.org/2016/10/30/i-dont-understand-asyncio/>`__,
   and there's a `widespread sense that we can do better
   <https://mail.python.org/pipermail/async-sig/2016-November/000175.html>`__.

   Trio is heavily inspired by Dave Beazley's `curio
   <https://github.com/dabeaz/curio>`__, and an analysis of how it
   `avoids many of the pitfalls of callback-based async programming
   models like asyncio
   <https://vorpus.org/blog/some-thoughts-on-asynchronous-api-design-in-a-post-asyncawait-world/>`__;
   trio tries to take these ideas further. Other influences include
   `C#, Erlang, and others
   <https://github.com/njsmith/trio/wiki/Reading-list>`__. But you
   don't need to know any of that to use trio.

   Our (possibly overambitious!) goal is that if you've previously
   used an async I/O library that was created in the pre-async/await
   era, then switching to trio should feel like switching from
   `urllib2 to requests
   <https://gist.github.com/kennethreitz/973705>`__, or from C to
   Python. Of course, whether we can live up to that is an open
   question! Trio represents one fairly opinionated vision for the
   future of asynchronous I/O in Python, but it's not the only such
   vision. If you're interested in trio, then you should certainly
   check out `asyncio
   <https://docs.python.org/3/library/asyncio.html>`__ and `curio
   <https://github.com/dabeaz/curio>`__ too.

   So... where to next?

   *I want to know more!* Check out the `documentation
   <https://trio.readthedocs.io>`__!

   *I want to dive in and try it!* Awesome! ``pip install trio`` and
   check out `our examples XX`. And if you use it for anything more
   than toy experiments, then you should `read and subscribe to this
   issue <https://github.com/njsmith/trio/issues/1>`__.

   *But wait, will it work on my system?* Probably! As long as you
   have either CPython 3.5+ or a PyPy 3.5 prerelease, and are using
   Linux, MacOS, or Windows, then trio should absolutely work. *BSD
   and illumos likely work too, but we don't have testing
   infrastructure for them.

   *I want to help!* You're the best! There's tons of work to do
   Check out our  <github issues>
   discussion, tests, docs, use it and let us know how it goes XX
   usability testing (try teaching yourself or a friend to use trio
   and make a list of every error message you hit and place where you
   got confused?), docs, logo, ...
   Depending on your interests, you might want to check out our lists
   of low-hanging fruit, of significant missing functionality, or of
   open high-level design questions.

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
   - KeyboardInterrupt handling
   - Synchronization primitives (Event, Queue, Semaphore, etc.)
   - Core socket handling

   Needs work:
   - IDNA (someone help me please)

   Needs written:
   - socket module:
     - sendfile
     - high level helpers like start_tcp_server
   - docs
   - subprocesses
   - worker process pool
   - SSL


   design/API principles:

   functions that take thunks (run, spawn, call_soon_threadsafe,
   run_in_thread, ...) all follow the pattern

   def caller(fn, *args_for_fn, **kwargs_for_caller)

   "notify"-style operations are sync-colored

   potentially-blocking operations always check for cancellation first,
   and always invoke the scheduler

   whenever possible, have a statistics() method that returns an
   immutable object with attributes that provide some useful stats --
   e.g. for a lock, number of waiters

   ``*_nowait``, ``trio.WouldBlock``

   ``wait_*``

   all async-colored primitives are unconditionally cancellation
   points and unconditionally invoke the scheduler.
   for non-primitives,
   => async means: at least sometimes invokes concurrency, suspension,
   cancellation

   only way to spawn is by having a nursery to spawn into

   admittedly this is a conceptual distinction rather than a strict
   technical one, e.g. we could set up a "spawn server" and then send
   spawn requests to it using synchronous calls to put_nowait, but we
   conjecture that it's a useful conceptual distinction.
   and in fact threads can do this!


   next:
   - arun/run/call_soon
     run/call/call_soon
     run/run_sync/(call_soon or run_sync_soon)
     run_async/run_sync

   - test helpers to explore all cancellation points?

   - a thought: if we switch to a global parkinglot keyed off of
     arbitrary hashables, and put the key into the task object, then
     introspection will be able to do things like show which tasks are
     blocked on the same mutex. (moving the key into the task object
     in general lets us detect which tasks are parked in the same lot;
     making the key be an actual synchronization object gives just a
     bit more information. at least in some cases; e.g. currently
     queues use semaphores internally so that's what you'd see in
     introspection, not the queue object.)

     alternatively, if we have an system for introspecting where tasks
     are blocked through stack inspection, then maybe we can re-use
     that? like if there's a magic local pointing to the frame, we can
     use that frame's 'self'?

   - blog post: a simple two-way proxy in both curio and trio
     (intentionally similar to the big blog post example)

     code is basically identical, but trio version:
     - correctly propagates errors
     - handles cancellations/timeouts
     - not subject to starvation
     - handles control-C

   - rename UnboundedQueue.get_all to UnboundedQueue.get_batch?

   - should we drop reap_and_unwrap? Is it really useful?

   - I looked at h2 and yeah, we definitely need to make stream have
     aclose() instead of close(). Sigh.
     ...If aclose is a cancellation point, does it need special
     cancellation semantics, like the mess around POSIX close? I'm
     leaning towards, for sockets it's implemented as

     async def aclose(self):
         self.close()
         await yield_briefly()

     ...but what about for other objects where closing really does
     require some work? __aexit__ in general has a problem here.

     in, like, an HTTP/2 server, you can't just defer cancellation
     while doing await sendall(channel_close_frame), because you've
     just made your timeouts ineffective and put yourself at the mercy
     of the remote server. So maybe the rule is you need a with on the
     socket *and* an async with on the stream, where the with on the
     socket does the rude cleanup (if necessary).

     Or maybe stream needs a force_close() method. Or just a mandatory
     rule that when implementing aclose() you need some strategy for
     handling cancellation?

     or maybe we need some ugly way to force h2 channels to be sync
     closeable. we just set a flag, someone else's job to force it
     out?

     it's a problem in general for any kind of async cleanup: how do
     you set a timeout on the cancellation handling?

   - make assert_yields properly check for cancel+schedule points
     put a counter of how many time these things happen on task object

   - add assert_yields tests to test_io

   - need to do a pass over TrioInternalError -- currently they can
     get double-wrapped in some cases

   - Python 3.7 wishlist items:

     - __iterclose__
     - better ergonomics for MultiErrors (catching, printing,
       rethrowing...)
       - concatenating tracebacks
       - attaching attributes to tracebacks (probably: subclassing them)
       - better control over implicit exception chaining

         example of a case that's simply broken and unfixable:

         v = ValueError()
         v.__context__ = KeyError()
         def discard_NameError(exc):
             if isinstance(exc, NameError):
                 return None
             return exc
         with pytest.raises(ValueError) as excinfo:
             with MultiError.catch(discard_NameError):
                 raise MultiError([v, NameError()])
         assert isinstance(excinfo.value.__context__, KeyError)
         assert not excinfo.value.__suppress_context__

         because Python *will* overwrite the ValueError's __context__
         in the catch's __exit__, even though it's already
         set. There's no way to stop it.

       - better hooks to control exception printing?
     - context chaining for .throw() and .athrow()
     - preserve the stack for yield from generators/coroutines, even
       when suspended -- XX no! you can recover this via cr_await! see
       curio.monitor._get_stack.
     - better support for KI management (in particular for __(a)exit__
       blocks, with their currently unfixable race condition)
       need to understand this better...

       Interesting comment in ceval.c:

            if (_Py_OPCODE(*next_instr) == SETUP_FINALLY) {
                /* Make the last opcode before
                   a try: finally: block uninterruptible. */
                goto fast_next_opcode;
            }

       it looks like:
       - for sync context managers, SETUP_WITH atomically calls
         __enter__ + sets up the finally block (though of course you
         could get a KI inside __enter__ if we don't have atomic KI
         protection)
       - for async context managers, the async setup stuff is split
         over multiple bytecodes, so we lose this guarantee -- it's
         possible for a KI to arrive in between calling __aenter__ and
         the SETUP_ASYNC_WITH that pushes the finally block
       - for sync context managers, WITH_CLEANUP_START atomically
         calls __exit__
       - for async context managers, there again are multiple
         bytecodes (WITH_CLEANUP_START calls __aenter__ (i.e.,
         instantiates the coroutine object), then GET_AWAITABLE calls
         __await__, then LOAD_CONST for some reason (??), then
         YIELD_FROM to actually run the __aenter__ body

       also of course we would need to fix
       contextmanager/acontextmanager so that the outermost
       __(a){enter,exit}__ actually are protected when they should be.

     - ability to go from stack frame to function object (maybe the
       frame itself could hold a pointer to the function, if
       available? no circular references that way. though putting it
       in the code object would probably be simpler otherwise.)
       used for:
         - better introspection (right now you can't get
           __qualname__ for tracebacks!)
         - patching the KI protection gap (I think, assuming 'with'
           calls __(a)exit__ atomically)
   - XX add a nursery fixture for pytest

     this is a bit complicated because it requires some tight
     integration with trio_test...

   - add an instrument hook for task created, task died, (task reaped?)

   - add nursery statistics? add a task statistics method that also
     gives nursery statistics? "unreaped tasks" is probably a useful
     metric... maybe we should just count that at the runner
     level. right now the runner knows the set of all tasks, but not
     zombies.

   - make sure to @ki_protection_enabled all our __(a)exit__
     implementations. Including @acontextmanager! it's not enough to
     protect the wrapped function. (Or is it? Or maybe we need to do
     both? I'm not sure what the call-stack looks like for a
     re-entered generator... and ki_protection for async generators is
     a bit of a mess, ugh. maybe ki_protection needs to use inspect to
     check for generator/asyncgenerator and in that case do the local
     injection thing. or maybe yield from.)

     I think there is an unclosable loop-hole here though b/c we can't
     enable @ki_protection atomically with the entry to
     __(a)exit__. If a KI arrives just before entering __(a)exit__,
     that's OK. And if it arrives after we've entered and the
     callstack is properly marked, that's also OK. But... since the
     mark is on the frame, not the code, we can't apply the mark
     instantly when entering, we need to wait for a few bytecode to be
     executed first. This is where having a bytecode flag or similar
     would be useful. (Or making it possible to attach attributes to
     code objects. I guess I could violently subclass CodeType, then
     swap in my new version... ugh.)

     I'm actually not 100% certain that this is even possible at the
     bytecode level, since exiting a with block seems to expand into 3
     separate bytecodes?

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

   - convenience methods for catching/rethrowing parts of MultiErrors?

     maybe

     def filter():
         try:
             yield
         except ...:
             ...
         except ...:
             ...
     with MultiError.filter(filter):
         ...

     calls the filter function repeatedly for each error inside the
     MultiError (or just once if a non-MultiError is raised), then
     collects the results.

   - notes for unix socket server:

     https://github.com/python/asyncio/issues/425
     Twisted uses a lockfile:
     https://github.com/twisted/twisted/blob/trunk/src/twisted/internet/unix.py#L290
     https://github.com/tornadoweb/tornado/blob/master/tornado/netutil.py#L215

   - XX add test for UnboundedQueue schedules properly (only wakes 1
     task if 2 puts)

   - factor call_soon machinery off into its own object

   - On UDP send libuv seems to dispatch sends immediately without any
     backpressure

   - Libuv uniformly *disables* v6only

   - Libuv UDP has some complicated handling of
     SetFileCompletionNotificationModes (they want to handle
     synchronous completions synchronously, but apparently there are
     bugs)

   - Linux sendall should temporarily disable notsent_lowat

   - Wondering if I should rename run->await_, and
     call_soon->run_soon. Maybe sync_await or something?

     or maybe await_in...->run_in..., and run_in...->call_in...?

   - Currently libuv uses neither SO_REUSEADDR, SO_EXCLUSIVEADDR,
     because they want to allow rebinding of TIME_WAIT sockets. But
     then there's https://github.com/joyent/libuv/issues/150

   - Libuv on Windows actually issues multiple AcceptEx calls
     simultaneously (optionally)

   - There is some mess around cancellation and LSPs... If a "non-IFS
     LSP" is installed then libuv uses wsaioctl to get the base handle
     before trying to cancel things
     http://www.komodia.com/KomodiaLSPTypes.pdf
     http://www.lenholgate.com/blog/2017/01/setfilecompletionnotificationmodes-can-cause-iocp-to-fail-if-a-non-ifs-lsp-is-installed.html

   - start_* convention -- if you want to run it synchronously, do
     async with make_nursery() as nursery:
         task = await start_foo(nursery)
     return task.result.unwrap()
     we might even want to wrap this idiom up in a convenience function

     for our server helper, it's a start_ function
     maybe it takes listener_nursery, connection_nursery arguments, to let you
     set up the graceful shutdown thing? though draining is still a
     problem. I guess just a matter of setting a deadline?

   - should we provide a start_nursery?

     problem: an empty nursery would close itself before start_nursery
     even returns!

     maybe as minimal extension to the existing thing,
     open_nursery(autoclose=False), only closes when cancelled?

   - algorithm for WFQ ParkingLot:

     if there are multiple tasks that are eligible to run immediately, then we
     want to wake the one that's been waiting longest (FIFO rule)
     otherwise, we want to wake the task that will be eligible to run first
     for each waiter, we know its entry time and its vtime
     we keep two data structures: one sorted by vtime, and one by entry
     time. Any given task is listed on *one* of these, not both! the vtime
     collection holds tasks that are not eligible to run yet (vtime in the
     future); the FIFO collection holds tasks that are eligible to run
     immediately (vtime in the past).
     to wake 1 task:
     - get the current vtime on the vclock
     - look at the set of tasks sorted by vtime, and for all the ones
       whose vtime is older than the current vtime, move them to the
       FIFO queue
     - pop from the FIFO queue
     - unless it's empty, in which case pop from the vtime queue
     this is something like amortized O(N log N) to queue/dequeue N tasks.

     HWFQ is... a much worse mess though, b/c a task could be eligible
     to run now but become ineligible before being scheduled :-(

   - according to the docs on Windows, with overlapped I/o you can
     still get WSAEWOULDBLOCK ("too many outstanding overlapped
     requests"). No-one on the internet seems to have any idea when
     this actually occurs or why. Twisted has a FIXME b/c they don't
     handle it, just propagate the error out.

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
   - pypy (but pypy has f-strings at least)

Code of conduct
---------------

Contributors are requested to follow our `code of conduct
<https://github.com/njsmith/trio/blob/master/CODE_OF_CONDUCT.md>`__ in
all project spaces.
