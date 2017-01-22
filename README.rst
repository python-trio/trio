nothing to see here

..
   Trio – async I/O for humans
   ===========================

   write apps that sing in three-part harmony

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
     - windows:
       - recvmsg_into
       - sendto
       - sendmsg
   - some sort of supervision story (+ probably want to change task API
     in the process)
   - docs
   - task-local storage
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
   - cancel_nowait should be idempotent... except for that awkward exc
     argument :-/
     also should probably just be called cancel
     alternatively, maybe we should allow it to be delivered multiple
     times? control-C can be hit multiple times... (I guess if one is
     pending and another arrives, the second overwrites the first?)

     also there's a problem right now where if we crash while some
     tasks are already unwinding from a (root) cancellation, then we
     try to cancel everyone and this errors out b/c they're already
     cancelled.

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

   - should probably throttle getaddrinfo threads

   - also according to the docs on Windows, with overlapped I/o you can
     still get WSAEWOULDBLOCK ("too many outstanding overlapped
     requests"). No-one on the internet seems to have any idea when
     this actually occurs or why. Twisted has a FIXME b/c they don't
     handle it, just propagate the error out.

   - should we split Queue and UnboundedQueue, latter has longer /
     more inconvenient name and only provides get_all and put_nowait,
     no put or get?

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

   - Note: I've seen KI raised purportedly inside call_soon_task, what's
     up with that?

   - testing KI manager, probably reworking some

   - sockets (need threads for getaddrinfo)

     - twisted is a nice reference for getaddrinfo -- e.g. they use some
       non-blocking numeric-only flags to handle some ipv6 corner
       cases.

     - ipv4 vs ipv6, ugh. create_connection should ideally support
       happy eyeballs, I guess?
       https://tools.ietf.org/html/rfc6555
       https://github.com/python/asyncio/issues/86
       https://twistedmatrix.com/documents/current/api/twisted.internet.endpoints.HostnameEndpoint.html
       https://github.com/crossdistro/netresolve

       https://www.akkadia.org/drepper/userapi-ipv6.html

   - kqueue power interface needs another pass + tests

   - async generator hooks

   - pytest plugin

   - task local storage
     - {run,await}_in_{worker,main}_thread should keep it! no concurrent
       access problem!
     - run_in_worker_process... hmm. pickleability is a problem.
       - trio.Local(pickle=True)?

   - do we need "batched accept" / socket.accept_nowait?
     (I suspect the same question applies for sendto/recvfrom)

     https://bugs.python.org/issue27906 suggests that we do
     and it's trivial to implement b/c it doesn't require any IOCP
     nonsense, just:

     try:
         return self._sock.accept()
     except BlockingIOError:
         raise _core.WouldBlock from None

     But...

     I am... not currently able to understand how/why this can
     help. Consider a simple model where after accepting each
     connection, we do a fixed bolus of CPU-bound work taking T
     seconds and then immediately send the response, so each
     connection is handled in a single loop step. If we accept only 1
     connection per loop step, then each loop step takes 1*T seconds
     and we handle 1 connection/T seconds on average. If we accept 100
     connections per loop step, then each loop step takes 100*T
     seconds and we handle 1 connection/T seconds on average.

     Did the folks in the bug report above really just need an
     increased backlog parameter to absorb bursts? Batching accept()
     certainly increases the effective listen queue depth (basically
     making it unlimited), but "make your queues unbounded" is not a
     generically helpful strategy.

     The above analysis is simplified in that (a) it ignores other
     work going on in the system and (b) it assumes each connection
     triggers a fixed amount of synchronous work to do. If it's wrong
     it's probably because one of these factors matters somehow. The
     "other work" part obviously could matter, *if* the other work is
     throttlable at the event loop level, in the sense that if loop
     steps take longer then they actually do less work. Which is not
     clear here (the whole idea of batching accept is make it *not*
     have this property, so if this is how we're designing all our
     components then it doesn't work...).

     I guess one piece of "other work" that scales with the number of
     passes through the loop is just, loop overhead. One would hope
     this is not too high, but it is not nothing.

   - possible improved robustness ("quality of implementation") ideas:
     - if an abort callback fails, discard that task but clean up the
       others (instead of discarding all)
     - if a clock raises an error... not much we can do about that.

   - debugging features:
     - traceback from task
     - get all tasks (for 'top' etc.) -- compare to thread iteration APIs
     - find the outermost frame of a blocked task that has a
       __trio_wchan__ annotation, and report it as the wchan (like
       curio's 'status' field)
       maybe wchan should be callable for details, so like
       run_in_worker_thread can show what's being run. or could just
       show the arguments I guess.

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
