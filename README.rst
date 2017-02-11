nothing to see here

..
   Trio – async I/O for humans and snake people
   ============================================

   Trio is an `async/await-native
   <https://vorpus.org/blog/some-thoughts-on-asynchronous-api-design-in-a-post-asyncawait-world/>`__
   I/O library for Python 3.5+ (either CPython or PyPy) with full
   support for Linux, MacOS, and Windows. (*BSD and illumos might work
   too, but we haven't checked.)

   [link to Guido's email]

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

   *I want to know more!* Check out the `documentation
   <https://trio.readthedocs.io>`.

   *I want to try it!* Awesome! ``pip install trio`` and check out
   `our examples XX`. And if you use it for anything more than toy
   experiments, then you should `read and subscribe to this issue
   <https://github.com/njsmith/trio/issues/1>`__.

   *I want to help!* You're the best! Check out our  <github issues>
   discussion, tests, docs, use it and let us know how it goes XX

   *I'm just fascinated by IO library design!* You might enjoy our <XX
   reading list> and XX architecture documentation

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
   - should system_task_wrapper by async?

   - dump Result.combine?

   - system_task_wrapper doesn't properly handle MultiError

   - should UnboundedQueue have logic to smooth out bursts to reduce
     latency spikes? e.g. if 1000 tasks die at time t and no tasks
     die at time t+1, t+2, t+3, then it would be better to reap, say,
     100 tasks each cycle.

     I'm not sure what the right control law for this is though.

   - [x] expose (hazmat) spawn_system_task
     [ ] then reimplement await_in_trio_thread... or whatever we want to
         call it

   - use an OrderedDict for call_soon(idempotent=True)
     however this is only possible on 3.6+! otherwise OrderedDict is
     not thread/signal-safe!

   - Should regular queues default to capacity=1? Should they even
     *support* capacity >1?

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

   - need to do a pass over TrioInternalError -- currently they can
     get double-wrapped in some cases

   - the MultiError handling in move_on_after is not so great --
     ideally we should at least preserve traceback? but *not* chain two
     giant almost-identical multi-errors?

   - Python 3.7 wishlist items:

     - __iterclose__
     - better ergonomics for MultiErrors (catching, printing,
       rethrowing...)
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

   - XX add a nursery fixture for pytest

     this is a bit complicated because it requires some tight
     integration with trio_test...

   - add an instrument hook for task created, task died, (task reaped?)

   - add nursery statistics? add a task statistics method that also
     gives nursery statistics? "unreaped tasks" is probably a useful
     metric... maybe we should just count that at the runner
     level. right now the runner knows the set of all tasks, but not
     zombies.

   - XX is there a better way to handle instrument errors than we
     currently do (print to stderr and carry on)?

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

     (Maybe the name for this is a Turnstile.)

     implementing a fair condition variable is also an interesting
     question -- you need to somehow move the tasks from waiting on
     the CV to waiting on the lock, preserving order and keeping
     cancellation working?
     https://amanieu.github.io/parking_lot/parking_lot_core/fn.unpark_requeue.html

     rwlocks too...
     https://amanieu.github.io/parking_lot/parking_lot/struct.RwLock.html

     ? https://amanieu.github.io/parking_lot/parking_lot_core/fn.unpark_filter.html

     a cute thing about classic parking lots (WTF, parking_lot.rs) is
     that it's a single global structure, to make individual
     synchronization objects cheaper; this is a win b/c most objects
     are uncontended most of the time, esp. when num_threads >>
     num_locks. Not totally clear how the trade-offs work for us.

     for reference:
     https://webkit.org/blog/6161/locking-in-webkit/

   - convenience methods for catching/rethrowing parts of MultiErrors?

   - notes for unix socket server:

     https://github.com/python/asyncio/issues/425
     Twisted uses a lockfile:
     https://github.com/twisted/twisted/blob/trunk/src/twisted/internet/unix.py#L290
     https://github.com/tornadoweb/tornado/blob/master/tornado/netutil.py#L215

   - XX add test for UnboundedQueue schedules properly (only wakes 1
     task if 2 puts)

     and also for __bool__

   - factor call_soon machinery off into its own object

   - super fancy MockClock: add rate and autojump_threshold properties

     rate = 0 is current; rate = <whatever> to go at arbitrary fixed
     speed

     autojump_threshold = *real* seconds where if we're idle that
     long, then we advance the clock to the next timeout

     to implement:

     add a threshold argument to wait_run_loop_idle

     implementation is basically: if there are no tasks to run, set
     the actual IO timeout as
       min(computed IO timeout, smallest wait_idle threshold)
     and if this is different than computed IO timeout, *and* there
     are no tasks to run after the IO manager returns, then wake all
     wait_idle tasks with the given threshold. (Or maybe just wake
     one? Or maybe you're just not even allowed to have multiple tasks
     in wait_run_loop_idle?)

     and when the clock's autojump_threshold is set to non-infinity,
     then it spawns a system task to sit on wait_run_loop_idle, and
     then somehow figure out the next deadline and jump there...

   - the example of why fairness is crucial:

     await mutex.acquire()
     while True:
         ...
         mutex.release()
         # currently, this always succeeds (!!):
         mutex.acquire_nowait()

     (right now it... kinda works if you do a blocking acquire,
     because it does reschedule before acquiring, so there's a 50%
     chance that the other task will run first and win the race. But
     50% is not so great either.)

   - Libuv check UDP sockets readable via iocp by issuing a 0 byte
     recv with MSG_PEEK (Even though msdn says you can't combine
     MSG_PEEK and overlapped mode!)  There is some complication
     because apparently this can return errors from sendto, but
     otherwise I guess it works for them. And they do something
     similar for TCP, but without the MSG_PEEK.

     (The reason they do this is also interesting -- if there are too
     many simultaneous recv calls outstanding then it uses too much
     buffer space, so they switch to waiting for readable before
     issuing the real recv.)

     Anyway I suspect but have not verified that this means you can
     use iocp to notify on:
     TCP readable, TCP writable, UDP readable
     ... But not UDP writable.
     (Then there's also raw sockets and stuff, no idea what happens
     there, though I guess it's probably like UDP)
     Oh wait! For UDP writable, MSG_PARTIAL might work!

     ...UDP send still has the problem that IOCP doesn't go through
     the socket buffer though, doh. it looks like some systems handle
     EWOULDBLOCK on UDP sends by just discarding the packet. the main
     thing we want to avoid is ending up with an arbitrarily long
     buffer in the kernel -- discarding packets *or* blocking the
     sending task are both fine. possibly we could handle IOCP UDP by
     just keeping a count of how many bytes are queued and put a limit
     on it? we could even intercept setsockopt SO_SNDBUF to control
     our user-space buffer size...

     for reading, this is apparently a well-known piece of folklore,
     the "zero byte read". It's related to a weird thing about IOCP
     where the receive buffers get pinned into memory, so official
     microsoft docs recommend it as a trick to avoid exhausting server
     memory when you have a ton of mostly-idle connections:

     https://www.microsoft.com/mspress/books/sampchap/5726a.aspx#124
     https://stackoverflow.com/questions/4988168/wsarecv-and-wsabuf-questions
     http://microsoft.public.win32.programmer.networks.narkive.com/l68NhvSm/wsarecv-iocp-when-exactly-is-the-notification-sent

     There is also this remarkable piece of undocumented sorcery:
     https://github.com/piscisaureus/epoll_windows/blob/master/src/epoll.c#L754
     https://groups.google.com/forum/#!topic/libuv/S4U_JjbxW9M
     http://mista.nu/blog/?p=655
     https://www.osronline.com/showthread.cfm?link=134510
     https://gist.github.com/daurnimator/63d2970aedc952f0beb3

   - add await_in_trio_thread back

   - Wsarcv also has a flag saying "please return data promptly, don't
     try to fill the buffer"; maybe that fixes the issue chrome ran
     into?

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

   - maybe system task is a new concept to replace the old one, where
     system tasks are parented by init, and if they crash then we
     cancel everything and raise

     ...in fact this is more or less the default behavior, except that
     we want to mark some errors as being internalerrors.

     ...and we want Cancelled exceptions to be propagated from
     call_soon tasks and main, but not from call_soon itself or the
     mock clock task...

   - start_* convention -- if you want to run it synchronously, do
     async with make_nursery() as nursery:
         task = await start_foo(nursery)
     return task.result.unwrap()
     we might even want to wrap this idiom up in a convenience function

     for our server helper, it's a start_ function
     maybe it takes listener_nursery, connection_nursery arguments, to let you
     set up the graceful shutdown thing? though draining is still a problem.

   - nurseries inside async generators are... odd. they *do* allow you
     to violate causality in the sense that the generator could be
     doing stuff while appearing to be yielded. I guess it still works
     out so long as the generator does eventually complete? if you
     leak this generator though then ugh what a mess. worst case we
     leak tasks -- the root task has exited, but there are still
     incomplete tasks floating around. not sure what we should do in
     that case. besides whine mightily.

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
