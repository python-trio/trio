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

   - thread helpers

     - thread pool: does two things
       1) put a limit on parallelism (semantics)
       2) re-use threads (optimization)

       getaddrinfo probably should have a bound on its parallelism?
       and it should be tunable? maybe a global bound on items that
       have a bound at all?

       for processes: obvs should be a bound and it should default to
       numcpus, easy
       for threads: I guess really there are two cases. case 1:
       threads which have an unbounded execution time and where that
       time might depend on other things inside the system that might
       also be calling run_in_worker_thread. Examples:
          - using a threading.Lock
          - waitpid() on a process
       these are also extremely low resource use, basically one
       blocking syscall.
       case 2: I/O bound threads that interact with the outside world,
       and will (probably) complete in reasonable, bounded time,
       regardless of what we do. Examples:
          - getaddrinfo
          - requests.get()

       run_in_worker_thread, run_in_waiter_thread?
       threading.Lock cases are ones where we also need to hold on to
       the thread for a while. run_in_worker_thread,
       get_or_spawn_worker_thread?
       curio has the name block_in_thread, which sounds nice (though
       it means something very different for them -- I'd have called
       it something like idempotent_in_thread...)
       wait_in_thread?

       you might want to say "reserve N threads for getaddrinfo,
       bursting up to M"?

       can't use concurrent.executors because:
          - it doesn't provide any fine-grained control over bounds
          - cancellation behavior is not so helpful (esp for
            ProcessPoolExecutor)

       sigh, I think I might have argued myself into having global
       thread&process pools instead of making them objects. So where
       do I put them? RunLocal? move them into core?

       https://twistedmatrix.com/documents/current/core/howto/threading.html
       twisted just doesn't have a way to allocate a new thread for an
       indefinitely blocking call. hmm.

       run_eventually_in_worker_thread

       run_in_worker_thread_queued
       run_in_worker_thread_now

       run_in_worker_thread
       run_in_sync_thread

       not really sure how important abide() or similar really is TBH.

       the blocking versions could potentially run with a tiny stack size
          ugh, the underlying APIs allow setting stack size on a
          per-thread basis, but Python only supports a single global.

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

   - should socket.bind be sync or async?

   - current_statistics() for runner stats
     number of tasks, number runnable, length of call_soon queue,
     whether crashed, ... and also calls iomanager.statistics()

   - kqueue power interface needs another pass + tests

   - async generator hooks

   - pytest plugin

   - task local storage
     - {run,await}_in_{worker,main}_thread should keep it! no concurrent
       access problem!
     - run_in_worker_process... hmm. pickleability is a problem.
       - trio.Local(pickle=True)?

   - possible improved robustness ("quality of implementation") ideas:
     - if an abort callback fails, discard that task but clean up the
       others (instead of discarding all)
     - if a profiler raises an exception, discard that profiler but
       continue
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

   - implement signal handling on top of new call_soon

   - implement {run,await}_in_main_thread on top of new call_soon

   - document the low-level API

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
