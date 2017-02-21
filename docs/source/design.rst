Design and internals
====================

Principles

Twin priorities: Usability and correctness

(What about performance? Nuanced.
Very important. But: 99th percentile latency more important than
throughput, and real-world speed more important than
microbenchmarks. Not interested in trying to build the fastest echo
server in the west.)

Specific notes

one of the hardest things is managing cancellation and concurrency.
correct code has to regularly check for cancellation, and has to
regularly yield to the event loop to maintain system
responsiveness. (so: you want more of these)
(these are linked because blocking operations have to be cancellation
points)
but these also create challenges -- handling cancellation is hard,
handling yields are hard
our strategy:
one exception: spawn

of course this isn't enough to guarantee correctness, still have to test

transparency: instrumentation hooks in the main loop to make it easy
to profile your app and track down CPU hogs
convention: statistics() method that reports things like number of
waiters

provide an excellent testing and debugging experience

stability: architectured for flexibility
-
just works out of the box - e.g. no picking between two
partially-working backends on Windows

other conventions:

- the ``fn(*args)`` convention

- tasks always complete; cleanups always run

- exceptions can never pass silently. in fact stronger: dumping some
  text to the console doesn't count. exceptions always **propagate**.
