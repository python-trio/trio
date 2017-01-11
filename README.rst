I/O for humans

emphasis on usability: goal is to help you write programs that are
safe, correct, low latency, high throughput
(in that order)

is it fast? it's not slow; for real optimization though going to wait
until we have real programs, b/c we'd rather not get into a fight over
who has the fastest echo server in the west.

minimal (TOOWTDI), layered design
(e.g., there is only one *built-in* synchronization primitive, the
ParkingLot; we provide the standard set of primitives like locks,
queues, etc. built on top of it, but you can pretty easily write your
own if you need them)

make it as easy as possible to reason about concurrency and
cancellation
documented which points are cancellation points, etc.
clear principles for which functions are async and which aren't

exceptions cannot pass silently

goals that we don't meet yet, but want to:
rigorous test suite
cross-platform
stable



design/API principles:

functions that take thunks (run, spawn, call_soon_threadsafe,
run_in_thread, ...) all follow the pattern

def caller(thunk, *args_for_thunk, *, **kwargs_for_caller)


"notify"-style operations are sync-colored

potentially-blocking operations always check for cancellation first,
and always invoke the scheduler
