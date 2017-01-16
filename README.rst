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
   - does it work?
   - async generator hooks
   - not 100% sure whether it makes sense to allow add_notify_queue
     after a task has exited? at that point it's too late to prevent a
     crash so... I guess maybe it's ok on the logic that the
     crash-prevention rule is you have to hvae at least one viewer
     before the task exits but you could have more later or not
     whatever.
   - not sure about exceptions thrown by run()... in particular, we don't
     wrap the main task's exceptions, because they might be normal. But
     if they're normal, and TaskCrashedErrors aren't normal, then we
     shouldn't allow main task exceptions to mask TaskCrashedErrors!
     But currently we do. At least... sort of. If the main task crashed
     first then there's no masking. If the main task crashed second, it
     was after being cancelled. (Though maybe it never saw the
     cancellation.)

     I think I prefer:
     - no special treatment for KeyboardInterrupt, supervisors are
       supposed to propagate it or whatever if that's what makes sense
     - we accumulate RunCrashedErrors separately from the initial task
       result, and combine them at the end, with RunCrashedError
       winning

     so complete set of things that can happen:
     - TrioInternalError: bug in trio; should never happen
     - KeyboardInterrupt: if you hit control-C *right* at the
       beginning or end of the run()
     - RunCrashedError: your code raised an exception that had
       no-where to propagate to or be handled, so for safety we bailed
       out
     - anything else: whatever your main function did

     (maybe we should have a way to propagate InternalError? like it
     should be impossible to get a CallSoonError from
     run_in_main_thread, so if you do...?)

   - pytest plugin
   - task local storage
     - {run,await}_in_{worker,main}_thread should keep it! no concurrent
       access problem!
     - run_in_worker_process... hmm. pickleability is a problem.
       - trio.Local(pickle=True)?
   - ability to process timeouts on demand for testing? (might make it
     easier to get weird cases like pending cancel that gets popped,
     anyway)
   - IOCP
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
