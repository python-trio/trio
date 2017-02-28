Design and internals
====================

.. currentmodule:: trio

Here we'll discuss Trio's overall design and architecture: how it fits
together and why we made the decisions we did. If all you want to do
is use Trio, then you don't need to read this – though you might find
it interesting. The main target audience here is (a) folks who want to
read the code and potentially contribute, (b) anyone working on
similar libraries who want to understand what we're up to, (c) anyone
interested in IO library design generally.

There are many valid approaches to writing an async IO library. This
is ours.


High-level design principles
----------------------------

Trio's two overriding goals are **usability** and **correctness**: we
want to make it *easy* to get things *right*.

Of course there are lots of other things that matter too, like speed,
maintainability, etc. We like those too, as much as we can get. But
sometimes these things come in conflict, and in those cases – while
there are never any absolute rules in engineering – these are our
priorities.

In some sense the entire rest of this document is a description of how
these play out, but to give a simple example: Trio's
``KeyboardInterrupt`` handling machinery is a bit tricky and hard to
test, so it scores poorly on simplicity and maintainability. But we
think the usability+correctness gains outweigh this.

There are some subtleties here. Notice that it's specifically "easy to
get things right". There are situations (e.g. writing one-off scripts)
where the most "usable" tool is the one that will happily ignore
errors and keep going no matter what, or that doesn't bother with
resource cleanup. (Cf. the success of PHP.) This is a totally valid
use case and valid definition of usability, but it's not the one we
use: we think it's easier to build reliable and correct systems if
exceptions propagate until handled and if the system `catches you when
you make potentially dangerous resource handling errors
<https://github.com/njsmith/trio/issues/23>`__, so that's what we
optimize for.

It's also worth saying something about speed, since it often looms
large in comparisons between I/O libraries. This is a rather subtle
and complex topic.

In general, speed is certainly important – but the fact that people
sometimes use Python instead of C is a pretty good indicator that
usability often trumps speed in practice. We want to make trio fast,
but it's not an accident that it's left off our list of overriding
goals at the top: if necessary we are willing to accept some slowdowns
in the service of usability and reliability.

To break things down in more detail:

First of all, there are the cases where speed directly impacts
correctness, like when you hit an accidental ``O(N**2)`` algorithm and
your program effectively locks up. Trio is very careful to use
algorithms and data structures that have good worst-case behavior
(even if this might mean sacrificing a few percentage points of speed
in the average case).

Similarly, when there's a conflict, we care more about (for example)
99th percentile latencies than we do about raw throughput, because
insufficient throughput – if it's consistent! – can often be budgeted
for and handled with horizontal scaling, but once you lose latency
it's gone forever, and latency spikes can easily cross over to become
a correctness issue (e.g., an RPC server that responds slowly enough
to trigger timeouts is effectively non-functional). Again, of course,
this doesn't mean we don't care about throughput – but sometimes
engineering requires making trade-offs, especially for early-stage
projects that haven't had time to optimize for all use cases yet.

And finally: we care about speed on real-world applications quite a
bit, but speed on microbenchmarks is just about our lowest
priority. We aren't interested in competing to build the fastest echo
server in the West. I mean, it's nice if it happens or whatever, and
microbenchmarks are an invaluable tool for understanding a system's
behavior. But if you play that game to win then it's very easy to get
yourself into a situation with seriously misaligned incentives, where
you have to start compromising on features and correctness in order to
get a speedup that's totally irrelevant to real-world applications. In
most cases (we suspect) it's the application code that's the
bottleneck, and you'll get more of a win out of running the whole app
under PyPy than out of any heroic optimizations to the IO
layer. (And this is why Trio *does* place a priority on PyPy
compatibility.)

As a matter of tactics, we also note that at this stage in Trio's
lifecycle, it'd probably be a mistake to worry about speed too
much. It doesn't make sense to spend lots of effort optimizing an API
whose semantics are still in flux.


User-level API
--------------

Explicit is better than implicit
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- the blog post & curio

  no implicit concurrency -- no callbacks, no implicit spawn, no
  implicit yield

  when you call a function it runs and then returns, like Guido
  intended


Cancel points and schedule points
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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


  There are a few exceptions to this rule:

  * async context managers: Context managers are composed of two
    operations – enter and exit – and sometimes only one of these is
    potentially blocking. But, Python doesn't have "half-asynchronous"
    context managers: either both operations are async-flavored, or
    neither is. In Trio we take a pragmatic approach: if for a
    particular construct there's only one operation that might block,
    then only that operation is a cancel+schedule point.

    Examples: ``async with lock:`` can block when entering but never
    when exiting; ``async with open_nursery() as ...:`` can block when
    exiting but never when entering.

  * async cleanup functions, like asynchronous versions of ``close``:
    These have a special rule: they can be cancelled, but they're
    always guaranteed to complete even if they are cancelled, though
    possibly in a rude way (so e.g. if you have a TLS stream and do
    ``await stream.graceful_close()``, and it's cancelled, then it
    will abandon the graceful shutdown and instead forcibly close the
    underlying socket before returning).

  * There are a few rare operations where fully implementing Trio's
    cancellation semantics are impossible, in particular
    :func:`trio.run_in_worker_thread` and
    :func:`trio.socket.SocketType.connect`. These are documented


Exceptions always propagate
~~~~~~~~~~~~~~~~~~~~~~~~~~~

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


Introspection and debugging
~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Introspection as a first class concern


API style guidelines
--------------------

``fun, *args``

statistics

wait

``X_nowait``



Implementation decisions
------------------------

- design for stability

  noticed that lots of interesting experiments in curio involve
  stuff like new synchronization primitives which require
  touching
  and

  hazmat layer: make it possible to implement new features
  without touching the core
  stable, public, but `nasty big pointy teeth <https://en.wikipedia.org/wiki/Rabbit_of_Caerbannog>`__

low-level IO:

- need to be portable

- need to expose/take advantage of the full capabilities of each
  system

- should "just work"

- a library isn't usable if it doesn't run on your system, or is
  missing features you need

  -> do our own low-level IO; expose the full capabilities of the
  underlying system

  (as of 2017-02-16, libuv is not able to support our rich
  cancellation semantics)

should "just work" out of the box





- KI: very challenging case for usability + correctness!

  challenging cases:

  - core run loop itself
  - synchronization primitives

  our solution


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
