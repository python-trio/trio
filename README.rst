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

   The ideas behind trio come most directly from `analyzing the
   pitfalls of callback-based async programming models like asyncio
   <https://vorpus.org/blog/some-thoughts-on-asynchronous-api-design-in-a-post-asyncawait-world/>`__,
   with heavy influence from Dave Beazley's `curio
   <https://github.com/dabeaz/curio>`__ (though trio and curio differ
   in fundamental enough ways that a new library seemed
   necessary). Other influences include `C#, Erlang, and others
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
   - MultiError.acatch -- also tracebacks are quite a pain if
     replacing one object by another... I guess each time we
     catch/rethrow, push the tracebacks from the MultiError onto the
     individual exceptions and then make a new MultiError?

     arun/run/call_soon
     run/call/call_soon
     run/run_sync/(call_soon or run_sync_soon)
     run_async/run_sync

     design document outline:

     target audience: folks who want to read the code and potentially
     contribute, folks working on competing libraries looking for
     ideas to steal, folks who are interested in IO library design generally

     -- high level --

     - priorities: usability and correctness

       usability means: assume user is going to take the trouble to
       get all the anal details right, and then make that as easy as
       possible

       if the user *wants* to be sloppy that's fine too, it's a
       reasonable decision, but we don't optimize for sloppy code

       what about speed?

       if you have a problem where speed is more important than
       usability, then you're probably not using Python in the first
       place, so...

     - a library isn't usable if it doesn't run on your system, or is
       missing features you need

       -> do our own low-level IO; expose the full capabilities of the
       underlying system

       (as of 2017-02-16, libuv is not able to support our rich
       cancellation semantics)

     - design for stability

       noticed that lots of interesting experiments in curio involve
       stuff like new synchronization primitives which require
       touching
       and

       hazmat layer: make it possible to implement new features
       without touching the core
       stable, public, but `nasty big pointy teeth <https://en.wikipedia.org/wiki/Rabbit_of_Caerbannog>`__

     -- user API --

     - the blog post & curio

       no implicit concurrency -- no callbacks, no implicit spawn, no
       implicit yield

       when you call a function it runs and then returns, like Guido
       intended

     - strong API conventions about cancel points and schedule points
       (major departure from curio)


       A cancel point is a point where your code checks if it has been
       cancelled – e.g., due to a timeout having expired – and
       potentially raises a ``Cancelled`` error. A schedule point is a
       point where the current task can potentially be suspended, and
       another task allowed to run.

       When writing async code, you need to be aware of cancel and
       schedule these points, because they introduce a set of complex
       and partially conflicting constraints:

       You need to make sure that every task passes through a cancel
       point regularly, because otherwise timeouts become ineffective
       and your code becomes subject to DoS attacks and other
       problems. So for correctness, it's important to make sure you
       have enough cancel points.

       But... every cancel point also increases the chance of subtle
       bugs in your program, because it's a place where you have to be
       prepared to handle a ``Cancelled`` exception and clean up
       properly. And while we try to make this as easy as possible,
       these kinds of clean-up paths are notorious for getting missed
       in testing and harboring subtle bugs. So the more cancel points
       you have, the harder it is to make sure your code is correct.

       Similarly, you need to make sure that every task passes through
       a schedule point regularly, because otherwise this task could
       end up hogging the event loop and preventing other code from
       running, causing a latency spike. So for correctness, it's
       important to make sure you have enough schedule points.

       But... you have to be careful here too, because every schedule
       point is a point where arbitrary other code could run, and
       alter your program's state out from under you, introducing
       classic concurrency bugs. So as you add more schedule points,
       it `becomes exponentially harder to reason about how your code
       is interleaved and be sure that it's correct
       <https://glyph.twistedmatrix.com/2014/02/unyielding.html>`__.

       Trio's approach is informed by two further observations:

       First, any time a task blocks (e.g., because it does an ``await
       sock.recv()`` but there's no data available to receive), that
       has to be a cancel point (because if the IO never arrives, we
       need to be able to time out), and it has to be a schedule point
       (because the whole idea of asynchronous programming is that
       when one task is waiting we can switch to another task to get
       something useful done).

       And second, a function which sometimes counts as
       cancel/schedule point, and sometimes doesn't, is the worst of
       both worlds: you have to be prepared to handle cancellation or
       interleaving, but you can't be sure that this will actually



       Every point that is a cancel point is also a schedule point,
       and vice versa. These are distinct concepts both theoretically
       and in the actual implementation, but we hide that distinction
       from the user so that there's only one concept they need to
       keep track of. (Exception: some hazmat APIs.)

       Any operation that *sometimes* blocks is *always* a cancel
       point and a schedule point.

       Operations that *never* block are *never* a cancel point or a
       schedule point.



       Exceptions:

       * async context managers: Context managers are composed of two
         operations – enter and exit – and sometimes only one of these
         is potentially blocking. But, Python doesn't have
         "half-asynchronous" context managers: either both operations
         are async, or neither is.

         (Examples: ``async with lock:`` can block when entering but
         never when exiting; ``async with open_nursery() as ...:`` can
         block when exiting but never when entering.)

       * run in thread

       * async close

       * socket.connect: can get into a state where it can't be
         cancelled; if so then closes socket on the way out

     - exceptions always propagate

       which leads to nursery design

       (influenced by erlang's link + monitor; we also have monitor,
       but our link is very different)

       this also gives a really neat invariant: any async function can
       use concurrency *within* itself *but* it has to be wrapped up
       before it returns.

       if you want concurrency that lasts beyond a function call
       ("causality violation"), then you need to somehow have a
       supervisor passed in

     - cancellation: fundamental & error prone
       we have this nice stack, want to be composable and allow
       cancellation/timeouts for arbitrary code

       combines curio's stack-based cancellation + new twist that
       stacks extend across tasks + C# style level-triggering

       potentially controversial: making them implicit/ambient instead
       of explicit. rationale: you have to pass them to literally
       every blocking operation, meaning that you would literally need
       every single async function to take this as an argument

     - Introspection as a first class concern

     - clean API with consistent conventions

     - KI: very challenging case for usability + correctness!

       challenging cases:

       - core run loop itself
       - synchronization primitives

       our solution

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
     - context chaining for .throw() and .athrow()
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

   - investigate:

     # this is fairly reproducible under pypy
     # ...and I also managed under cpython!
     ~/trio$ /tmp/pypy-c-jit-90116-b30c111d304e-linux64/bin/pypy3 -m vmprof --web schedule-timing.py
       53714.35373615269 loops/sec
       90986.52576135045 loops/sec
       92658.02343558217 loops/sec
       93007.6548706217 loops/sec
       93864.61163651443 loops/sec
       93248.05561866662 loops/sec
       94092.07741495097 loops/sec
       94105.7938769012 loops/sec
       92232.44120369531 loops/sec
       ^CTraceback (most recent call last):
         File "/home/njs/trio/trio/_core/_run.py", line 774, in run
           result = run_impl(runner, fn, args)
         File "/home/njs/trio/trio/_core/_run.py", line 874, in run_impl
           runner.task_finished(task, final_result)
         File "/home/njs/trio/trio/_core/_run.py", line 518, in task_finished
           task._cancel_stack[-1]._remove_task(task)
         File "/home/njs/trio/trio/_core/_run.py", line 156, in _remove_task
           self._tasks.remove(task)
         File "/tmp/pypy-c-jit-90116-b30c111d304e-linux64/lib-python/3/contextlib.py", line 66, in __exit__
           next(self.gen)
         File "/home/njs/trio/trio/_core/_run.py", line 110, in _might_change_effective_deadline
           del runner.deadlines[old, id(self)]
         File "/tmp/pypy-c-jit-90116-b30c111d304e-linux64/site-packages/sortedcontainers/sorteddict.py", line 165, in __delitem__
           self._delitem(key)
       KeyError: (-inf, 61061952)

       The above exception was the direct cause of the following exception:

       Traceback (most recent call last):
         File "/tmp/pypy-c-jit-90116-b30c111d304e-linux64/lib-python/3/runpy.py", line 193, in _run_module_as_main
           "__main__", mod_spec)
         File "/tmp/pypy-c-jit-90116-b30c111d304e-linux64/lib-python/3/runpy.py", line 85, in _run_code
           exec(code, run_globals)
         File "/tmp/pypy-c-jit-90116-b30c111d304e-linux64/site-packages/vmprof/__main__.py", line 75, in <module>
           main()
         File "/tmp/pypy-c-jit-90116-b30c111d304e-linux64/site-packages/vmprof/__main__.py", line 61, in main
           runpy.run_path(args.program, run_name='__main__')
         File "/tmp/pypy-c-jit-90116-b30c111d304e-linux64/lib-python/3/runpy.py", line 263, in run_path
           pkg_name=pkg_name, script_name=fname)
         File "/tmp/pypy-c-jit-90116-b30c111d304e-linux64/lib-python/3/runpy.py", line 96, in _run_module_code
           mod_name, mod_spec, pkg_name, script_name)
         File "/tmp/pypy-c-jit-90116-b30c111d304e-linux64/lib-python/3/runpy.py", line 85, in _run_code
           exec(code, run_globals)
         File "schedule-timing.py", line 37, in <module>
           trio.run(main)
         File "/home/njs/trio/trio/_core/_run.py", line 777, in run
           "internal error in trio - please file a bug!") from exc
       trio._core._exceptions.TrioInternalError: internal error in trio - please file a bug!
       ~/trio$

     here's a different one:

     ~/trio$ python schedule-timing.py
     15356.528164786758 loops/sec
     15097.020960402195 loops/sec
     15128.185759201793 loops/sec
     14795.546545012578 loops/sec
     15001.787497052788 loops/sec
     15279.823309439222 loops/sec
     14684.291508136756 loops/sec
     14522.351898311712 loops/sec
     ^CTraceback (most recent call last):
       File "/home/njs/trio/trio/_core/_run.py", line 774, in run
         result = run_impl(runner, fn, args)
       File "/home/njs/trio/trio/_core/_run.py", line 875, in run_impl
         runner.task_finished(task, final_result)
       File "/home/njs/trio/trio/_core/_run.py", line 518, in task_finished
         task._cancel_stack[-1]._remove_task(task)
       File "/home/njs/trio/trio/_core/_run.py", line 156, in _remove_task
         self._tasks.remove(task)
     KeyError: <Task with coro=<coroutine object reschedule_loop at 0x7f582b5c6f10>>

     The above exception was the direct cause of the following exception:

     Traceback (most recent call last):
       File "schedule-timing.py", line 37, in <module>
         trio.run(main)
       File "/home/njs/trio/trio/_core/_run.py", line 777, in run
         "internal error in trio - please file a bug!") from exc
     trio._core._exceptions.TrioInternalError: internal error in trio - please file a bug!
     [then a bunch of chatter from __del__ assertions]
     ~/trio$


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

   - can we remove all busy_wait_for in favor of wait_run_loop_idle?

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
