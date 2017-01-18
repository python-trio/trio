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
   - really need a good convention for naming functions that return
     when some condition is true. 'await readable()' sounds okay but
     is totally ambiguous about whether it's waiting for readable to
     be true or returning a boolean telling whether readable is true,
     and the latter has more weight of precedent behind it.
     I tried 'await until_readable' but it hasn't grown on me as much
     as I was hoping -- the 'await' disappears, and it usually looks
     more like 'await sock.until_readable()' which reads horribly
     anyway.

        await sock.wait_readable()
        await sock.require_readable()
        await sock.demand_readable()
        await sock.guarantee_readable()

     vow? insist? also these all sound like assertions :-(

   - join returning result is actually pretty bad because it
     encourages

        await task.join()

     to wait for a task that "can't fail"... but if it does then this
     silently discards the exception :-( :-(
   - async generator hooks
   - pytest plugin
   - task local storage
     - {run,await}_in_{worker,main}_thread should keep it! no concurrent
       access problem!
     - run_in_worker_process... hmm. pickleability is a problem.
       - trio.Local(pickle=True)?
   - profiler is a bad name for what it is... tracer? monitor? --
     instruments
     - other things to instrument:
       - reschedule
       - start of batch, length of runq, length of time in io handler
   - IOCP
   - possible improved robustness ("quality of implementation") ideas:
     - if an abort callback fails, discard that task but clean up the
       others (instead of discarding all)
     - if a profiler raises an exception, discard that profiler but
       continue
     - if a clock raises an error... not much we can do about that.
   - debugging features:
     - traceback from task
     - get all tasks (for 'top' etc.)
     - find the outermost frame of a blocked task that has a
       __trio_wchan__ annotation, and report it as the wchan (like
       curio's 'status' field)
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
