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

   - should sock.bind() be sync or async? It is weird because in
     99.999% of usual uses, you pass in "" or at worst "localhost",
     and the name is resolved instantly without hitting the
     network. But if you *do* pass in something else, then it will do
     a full blocking DNS query etc. (And I guess this even could
     succeed, if someone has an A/AAAA record pointing to one of the
     local interfaces.)

     And isn't really any way to detect ahead of time if this is going
     to happen -- we can't tell a priori whether "localhost6" say is
     in the local hosts file, and there's no way to tell the resolver
     "please don't use the network". (You can tell it "please reject
     names", but people might reasonably get grumpy if they can't say
     "localhost". or maybe this is a teaching opportunity?)

     leaning towards requiring people to pass in numeric only (or
     wildcard), and telling them to call getaddrinfo themselves if
     that's what they want.

   - IOCP + UDP on Windows is pretty badly broken: for UDP Windows
     waits to signal the operation complete until the packet is
     actually transmitted, as opposed to when it gets copied into the
     kernel buffer:
       https://bugs.chromium.org/p/chromium/issues/detail?id=442392
       https://groups.google.com/a/chromium.org/forum/#!topic/net-dev/VTPH1D8M6Ds
     the solution chrome came up with was to switch to using
     select+nonblocking I/O for UDP sockets.
     (apparently they also use this for tcp receive?)
     OMG: https://bugs.chromium.org/p/chromium/issues/detail?id=30144#
     https://bugs.chromium.org/p/chromium/issues/detail?id=86515#
     IOCP recv will just sit on buffers before handing them back if it
     thinks your buffer was too big

     So maybe we do need to come up with a way to run select in a
     thread in Windows... it's annoying but would also give us
     wait_maybe_writable?

     alternatively I guess the correct way to write IOCP+UDP code is
     to implement our own send buffer, where we spam out packets
     without waiting for the previous one to complete, until we have a
     certain number (how many?) outstanding
     (Maybe this is why the WSASendMsg docs actually say that you can
     get WSAEWOULDBLOCK if "there are too many outstanding overlapped
     I/O requests"? It would be convenient if WSAEWOULDBLOCK was
     signalled when the UDP send buffer was full, but who knows if
     that's true.)

     or do non-blocking send until we get WSAEWOULDBLOCK, and then
     issue an overlapped send? this is still suboptimal though b/c
     we'll get a little pipeline stall after each overlapped call.

     it looks like:
     - there isn't any actual limit on the number of sockets you can
       pass to select() or WSAPoll() (though python's select.select
       wrapper tops out at 512).
     - alternatively, there's also WSAEventSelect, which is a bit
       tricky because it's event-triggered (sorta -- read the MSDN
       page carefully for details), but I guess we've ended up
       in a place where we never block on wait_{read,writ}able unless
       we've just failed to recv/send, so that's fine.

       this is useful if we end up implementing a proper event-waiting
       system for other reasons. WaitForMultipleObjects is much less
       scalable than WSAPoll though (64 events vs
       limited-by-O(n)-behavior)

     the challenge of running WSAWaitForMultipleEvents + WSAPoll +
     IOCP at the same time is that you need a way to wake up the main
     thread when one of the child threads detects something, and you
     need a way to wake up the child threads when you want to
     add/remove something from their set.

     IOCP is easy, you can post to it whenever from where-ever

     WSAPoll with a negative timeout ("wait forever") is alertable, so
     you can do QueueUserAPC to wake it up on demand.

     WSAWaitForMultipleEvents is also alertable (optionally)

     (I guess WaitForMultipleObjectsEx and WSAWaitForMultipleEvents are
     like... the same function?)

     so one design would be:
       - keep IOCP in the main thread
       - dedicate two completion keys to poll and event data
       - spawn two threads to sit in those
       - when we want to add an object to the watched sets, drop it on
         a queue and post an APC to the relevant thread
         - or maybe batch up the APC so as to only do it when
           handle_io is called, no point in doing it before that
       - whenever they wake up, they immediately:
         - post back any events to the IOCP, payload is a few
           integers, no problem
         - read out the queue, update their watchlists
         - go back to sleep

     there are some funny race condition issues if, like, the IOCP
     wait returns immediately but the WSAPoll wait hasn't quite gotten
     started yet, how do we know whether to wait...? maybe they do a
     timeout zero, report back that they've done so, and then go to
     sleep for real?

     maybe (ignoring WaitForMultipleObjectsEx for the moment):

       - do a timeout 0 WSAPoll
       - pass the WSAPoll structures over to the thread
       - do a timeout X IOCP

     or maybe it's better the other way around -- ask the thread to do
     its thing, go to sleep, and then after waking up do a manual
     WSAPoll to make sure we've got an up-to-date snapshot?

     not entirely clear that it's worth messing with
     WaitForMultipleObjectsEx as opposed to just dedicating a thread
     per object waited on.

     huh, select's socket sets are actually pretty easy to work with,
     maybe easier than WSAPoll (esp. if we are in the regime where
     we're recreating the objects every time)

       typedef struct fd_set {
        u_int fd_count;               /* how many are SET? */
        SOCKET  fd_array[FD_SETSIZE];   /* an array of SOCKETs */
       } fd_set;

     select() isn't alertable, though, so would need to use the
     socketpair trick.

   - should probably throttle getaddrinfo threads

   - also according to the docs on Windows, with overlapped I/o you can
     still get WSAEWOULDBLOCK ("too many outstanding overlapped
     requests"). No-one on the internet seems to have any idea when
     this actually occurs or why. Twisted has a FIXME b/c they don't
     handle it, just propagate the error out.

   - should we have "batched accept"?

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

   - do we need a socket.accept_nowait?

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
