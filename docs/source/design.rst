Design and internals
====================

.. currentmodule:: trio

Here we'll discuss Trio's overall design and architecture: how it fits
together and why we made the decisions we did. If all you want to do
is use Trio, then you don't need to read this – though you might find
it interesting. The main target audience here is (a) folks who want to
read the code and potentially contribute, (b) anyone working on
similar libraries who want to understand what we're up to, (c) anyone
interested in I/O library design generally.

There are many valid approaches to writing an async I/O library. This
is ours.


High-level design principles
----------------------------

Trio's two overriding goals are **usability** and **correctness**: we
want to make it *easy* to get things *right*.

Of course there are lots of other things that matter too, like speed,
maintainability, etc. We want those too, as much as we can get. But
sometimes these things come in conflict, and when that happens, these
are our priorities.

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
<https://github.com/python-trio/trio/issues/265>`__, so that's what we
optimize for.

It's also worth saying something about speed, since it often looms
large in comparisons between I/O libraries. This is a rather subtle
and complex topic.

In general, speed is certainly important – but the fact that people
sometimes use Python instead of C is a pretty good indicator that
usability often trumps speed in practice. We want to make Trio fast,
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

Similarly, when there's a conflict, we care more about 99th percentile
latencies than we do about raw throughput, because insufficient
throughput – if it's consistent! – can often be budgeted for and
handled with horizontal scaling, but once you lose latency it's gone
forever, and latency spikes can easily cross over to become a
correctness issue (e.g., an RPC server that responds slowly enough to
trigger timeouts is effectively non-functional). Again, of course,
this doesn't mean we don't care about throughput – but sometimes
engineering requires making trade-offs, especially for early-stage
projects that haven't had time to optimize for all use cases yet.

And finally: we care about speed on real-world applications quite a
bit, but speed on microbenchmarks is just about our lowest
priority. We aren't interested in competing to build "the fastest echo
server in the West". I mean, it's nice if it happens or whatever, and
microbenchmarks are an invaluable tool for understanding a system's
behavior. But if you play that game to win then it's very easy to get
yourself into a situation with seriously misaligned incentives, where
you have to start compromising on features and correctness in order to
get a speedup that's totally irrelevant to real-world applications. In
most cases (we suspect) it's the application code that's the
bottleneck, and you'll get more of a win out of running the whole app
under PyPy than out of any heroic optimizations to the I/O
layer. (And this is why Trio *does* place a priority on PyPy
compatibility.)

As a matter of tactics, we also note that at this stage in Trio's
lifecycle, it'd probably be a mistake to worry about speed too
much. It doesn't make sense to spend lots of effort optimizing an API
whose semantics are still in flux.


User-level API principles
-------------------------

Basic principles
~~~~~~~~~~~~~~~~

Trio is very much a continuation of the ideas explored in `this blog
post
<https://vorpus.org/blog/some-thoughts-on-asynchronous-api-design-in-a-post-asyncawait-world/>`__,
and in particular the `principles identified there
<https://vorpus.org/blog/some-thoughts-on-asynchronous-api-design-in-a-post-asyncawait-world/#review-and-summing-up-what-is-async-await-native-anyway>`__
that make curio easier to use correctly than asyncio. So Trio also
adopts these rules, in particular:

* The only form of concurrency is the task.

* Tasks are guaranteed to run to completion.

* Task spawning is always explicit. No callbacks, no implicit
  concurrency, no futures/deferreds/promises/other APIs that involve
  callbacks. All APIs are `"causal"
  <https://vorpus.org/blog/some-thoughts-on-asynchronous-api-design-in-a-post-asyncawait-world/#review-and-summing-up-what-is-async-await-native-anyway>`__
  except for those that are explicitly used for task spawning.

* Exceptions are used for error handling; ``try``/``finally``
  and ``with`` blocks for handling cleanup.


Cancel points and schedule points
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The first major place that Trio departs from curio is in its decision
to make a much larger fraction of the API use sync functions rather
than async functions, and to provide strong conventions about cancel
points and schedule points. (At this point, there are a lot of ways
that Trio and curio have diverged. But this was really the origin –
the tipping point where I realized that exploring these ideas would
require a new library, and couldn't be done inside curio.) The full
reasoning here takes some unpacking.

First, some definitions: a *cancel point* is a point where your code
checks if it has been cancelled – e.g., due to a timeout having
expired – and potentially raises a :exc:`Cancelled` error. A *schedule
point* is a point where the current task can potentially be suspended,
and another task allowed to run.

In curio, the convention is that all operations that interact with the
run loop in any way are syntactically async, and it's undefined which
of these operations are cancel/schedule points; users are instructed
to assume that any of them *might* be cancel/schedule points, but with
a few exceptions there's no guarantee that any of them are unless they
actually block. (I.e., whether a given call acts as a cancel/schedule
point is allowed to vary across curio versions and also depending on
runtime factors like network load.)

But when using an async library, there are good reasons why you need
to be aware of cancel and schedule points. They introduce a set of
complex and partially conflicting constraints on your code:

You need to make sure that every task passes through a cancel
point regularly, because otherwise timeouts become ineffective
and your code becomes subject to DoS attacks and other
problems. So for correctness, it's important to make sure you
have enough cancel points.

But... every cancel point also increases the chance of subtle
bugs in your program, because it's a place where you have to be
prepared to handle a :exc:`Cancelled` exception and clean up
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

So an important question for an async I/O library is: how do we help
the user manage these trade-offs?

Trio's answer is informed by two further observations:

First, any time a task blocks (e.g., because it does an ``await
sock.recv()`` but there's no data available to receive), that
has to be a cancel point (because if the I/O never arrives, we
need to be able to time out), and it has to be a schedule point
(because the whole idea of asynchronous programming is that
when one task is waiting we can switch to another task to get
something useful done).

And second, a function which sometimes counts as a cancel/schedule
point, and sometimes doesn't, is the worst of both worlds: you have
put in the effort to make sure your code handles cancellation or
interleaving correctly, but you can't count on it to help meet latency
requirements.

With all that in mind, Trio takes the following approach:

Rule 1: to reduce the number of concepts to keep track of, we collapse
cancel points and schedule points together. Every point that is a
cancel point is also a schedule point and vice versa. These are
distinct concepts both theoretically and in the actual implementation,
but we hide that distinction from the user so that there's only one
concept they need to keep track of.

Rule 2: Cancel+schedule points are determined *statically*. A Trio
primitive is either *always* a cancel+schedule point, or *never* a
cancel+schedule point, regardless of runtime conditions. This is
because we want it to be possible to determine whether some code has
"enough" cancel/schedule points by reading the source code.

In fact, to make this even simpler, we make it so you don't even have
to look at the function arguments: each *function* is either a
cancel+schedule point on *every* call or on *no* calls.

(Pragmatic exception: a Trio primitive is not required to act as a
cancel+schedule point when it raises an exception, even if it would
act as one in the case of a successful return. See `issue 474
<https://github.com/python-trio/trio/issues/474>`__ for more details;
basically, requiring checkpoints on all exception paths added a lot of
implementation complexity with negligible user-facing benefit.)

Observation: since blocking is always a cancel+schedule point, rule 2
implies that any function that *sometimes* blocks is *always* a
cancel+schedule point.

So that gives us a number of cancel+schedule points: all the functions
that can block. Are there any others? Trio's answer is: no. It's easy
to add new points explicitly (throw in a ``sleep(0)`` or whatever) but
hard to get rid of them when you don't want them. (And this is a real
issue – "too many potential cancel points" is definitely a tension
`I've felt
<https://github.com/dabeaz/curio/issues/149#issuecomment-269745283>`__
while trying to build things like task supervisors in curio.) And we
expect that most Trio programs will execute potentially-blocking
operations "often enough" to produce reasonable behavior. So, rule 3:
the *only* cancel+schedule points are the potentially-blocking
operations.

And now that we know where our cancel+schedule points are, there's the
question of how to effectively communicate this information to the
user. We want some way to mark out a category of functions that might
block or trigger a task switch, so that they're clearly distinguished
from functions that don't do this. Wouldn't it be nice if there were
some Python feature, that naturally divided functions into two
categories, and maybe put some sort of special syntactic marking on
with the functions that can do weird things like block and task
switch...? What a coincidence, that's exactly how async functions
work! Rule 4: in Trio, only the potentially blocking functions are
async. So e.g. :meth:`Event.wait` is async, but :meth:`Event.set` is
sync.

Summing up: out of what's actually a pretty vast space of design
possibilities, we declare by fiat that when it comes to Trio
primitives, all of these categories are identical:

* async functions
* functions that can, under at least some circumstances, block
* functions where the caller needs to be prepared to handle
  potential :exc:`Cancelled` exceptions
* functions that are guaranteed to notice any pending cancellation
* functions where you need to be prepared for a potential task switch
* functions that are guaranteed to take care of switching tasks if
  appropriate

This requires some non-trivial work internally – it actually takes a
fair amount of care to make those 4 cancel/schedule categories line
up, and there are some shenanigans required to let sync and async APIs
both interact with the run loop on an equal footing. But this is all
invisible to the user, we feel that it pays off in terms of usability
and correctness.

There is one exception to these rules, for async context
managers. Context managers are composed of two operations – enter and
exit – and sometimes only one of these is potentially
blocking. (Examples: ``async with lock:`` can block when entering but
never when exiting; ``async with open_nursery() as ...:`` can block
when exiting but never when entering.) But, Python doesn't have
"half-asynchronous" context managers: either both operations are
async-flavored, or neither is. In Trio we take a pragmatic approach:
for this kind of async context manager, we enforce the above rules
only on the potentially blocking operation, and the other operation is
allowed to be syntactically ``async`` but semantically
synchronous. And async context managers should always document which
of their operations are schedule+cancel points.


Exceptions always propagate
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Another rule that Trio follows is that *exceptions must always
propagate*. This is like the `zen
<https://www.python.org/dev/peps/pep-0020/>`__ line about "Errors
should never pass silently", except that in every other concurrency
library for Python (threads, asyncio, curio, ...), it's fairly common
to end up with an undeliverable exception, which just gets printed to
stderr and then discarded. While we understand the pragmatic
constraints that motivated these libraries to adopt this approach, we
feel that there are far too many situations where no human will ever
look at stderr and notice the problem, and insist that Trio APIs find
a way to propagate exceptions "up the stack" – whatever that might
mean.

This is often a challenging rule to follow – for example, the call
soon code has to jump through some hoops to make it happen – but its
most dramatic influence can seen in Trio's task-spawning interface,
where it motivates the use of "nurseries"::

   async def parent():
       async with trio.open_nursery() as nursery:
           nursery.start_soon(child)

(See :ref:`tasks` for full details.)

If you squint you can see the conceptual influence of Erlang's "task
linking" and "task tree" ideas here, though the details are different.

This design also turns out to enforce a remarkable, unexpected
invariant.

In `the blog post
<https://vorpus.org/blog/some-thoughts-on-asynchronous-api-design-in-a-post-asyncawait-world/#c-c-c-c-causality-breaker>`__
I called out a nice feature of curio's spawning API, which is that
since spawning is the only way to break causality, and in curio
``spawn`` is async, which means that in curio sync functions are
guaranteed to be causal. One limitation though is that this invariant
is actually not very predictive: in curio there are lots of async
functions that could spawn off children and violate causality, but
most of them don't, but there's no clear marker for the ones that do.

Our API doesn't quite give that guarantee, but actually a better
one. In Trio:

* Sync functions can't create nurseries, because nurseries require an
  ``async with``

* Any async function can create a nursery and start new tasks... but
  creating a nursery *allows task starting but does not permit
  causality breaking*, because the children have to exit before the
  function is allowed to return. So we can preserve causality without
  having to give up concurrency!

* The only way to violate causality (which is an important feature,
  just one that needs to be handled carefully) is to explicitly create
  a nursery object in one task and then pass it into another task. And
  this provides a very clear and precise signal about where the funny
  stuff is happening – just watch for the nursery object getting
  passed around.


Introspection, debugging, testing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tools for introspection and debugging are critical to achieving
usability and correctness in practice, so they should be first-class
considerations in Trio.

Similarly, the availability of powerful testing tools has a huge
impact on usability and correctness; we consider testing helpers to be
very much in scope for the Trio project.


Specific style guidelines
-------------------------

* As noted above, functions that don't block should be sync-colored,
  and functions that might block should be async-colored and
  unconditionally act as cancel+schedule points.

* Any function that takes a callable to run should have a signature
  like::

     def call_the_thing(fn, *args, kwonly1, kwonly2, ...)::
         ...

  where ``fn(*args)`` is the thing to be called, and ``kwonly1``,
  ``kwonly2``, ... are keyword-only arguments that belong to
  ``call_the_thing``. This applies even if ``call_the_thing`` doesn't
  take any arguments of its own, i.e. in this case its signature looks
  like::

     def call_the_thing(fn, *args)::
         ...

  This allows users to skip faffing about with
  :func:`functools.partial` in most cases, while still providing an
  unambiguous and extensible way to pass arguments to the caller.
  (Hat-tip to asyncio, who we stole this convention from.)

* Whenever it makes sense, Trio classes should have a method called
  ``statistics()`` which returns an immutable object with named fields
  containing internal statistics about the object that are useful for
  debugging or introspection (:ref:`examples <synchronization>`).

* Functions or methods whose purpose is to wait for a condition to
  become true should be called ``wait_<condition>``. This avoids
  ambiguities like "does ``await readable()`` *check* readability
  (returning a bool) or *wait for* readability?".

  Sometimes this leads to the slightly funny looking ``await
  wait_...``. Sorry. As far as I can tell all the alternatives are
  worse, and you get used to the convention pretty quick.

* If it's desirable to have both blocking and non-blocking versions of
  a function, then they look like::

     async def OPERATION(...):
         ...

     def OPERATION_nowait(...):
         ...

  and the ``nowait`` version raises :exc:`trio.WouldBlock` if it would block.

* ...we should, but currently don't, have a solid convention to
  distinguish between functions that take an async callable and those
  that take a sync callable. See `issue #68
  <https://github.com/python-trio/trio/issues/68>`__.


A brief tour of Trio's internals
--------------------------------

If you want to understand how Trio is put together internally, then
the first thing to know is that there's a very strict internal
layering: the ``trio._core`` package is a fully self-contained
implementation of the core scheduling/cancellation/IO handling logic,
and then the other ``trio.*`` modules are implemented in terms of the
API it exposes. (If you want to see what this API looks like, then
``import trio; print(trio._core.__all__)``). Everything exported from
``trio._core`` is *also* exported as part of the ``trio``,
``trio.lowlevel``, or ``trio.testing`` namespaces. (See their
respective ``__init__.py`` files for details; there's a test to
enforce this.)

Rationale: currently, Trio is a new project in a novel part of the
design space, so we don't make any stability guarantees. But the goal
is to reach the point where we *can* declare the API stable. It's
unlikely that we'll be able to quickly explore all possible corners of
the design space and cover all possible types of I/O. So instead, our
strategy is to make sure that it's possible for independent packages
to add new features on top of Trio. Enforcing the ``trio`` vs
``trio._core`` split is a way of `eating our own dogfood
<https://en.wikipedia.org/wiki/Eating_your_own_dog_food>`__: basic
functionality like :class:`trio.Lock` and :mod:`trio.socket` is
actually implemented solely in terms of public APIs. And the hope is
that by doing this, we increase the chances that someone who comes up
with a better kind of queue or wants to add some new functionality
like, say, file system change watching, will be able to do that on top
of our public APIs without having to modify Trio internals.


Inside ``trio._core``
~~~~~~~~~~~~~~~~~~~~~

There are two notable sub-modules that are largely independent of
the rest of Trio, and could (possibly should?) be extracted into their
own independent packages:

* ``_multierror.py``: Implements :class:`MultiError` and associated
  infrastructure.

* ``_ki.py``: Implements the core infrastructure for safe handling of
  :class:`KeyboardInterrupt`.

The most important submodule, where everything is integrated, is
``_run.py``. (This is also by far the largest submodule; it'd be nice
to factor bits of it out where possible, but it's tricky because the
core functionality genuinely is pretty intertwined.) Notably, this is
where cancel scopes, nurseries, and :class:`~trio.lowlevel.Task` are
defined; it's also where the scheduler state and :func:`trio.run`
live.

The one thing that *isn't* in ``_run.py`` is I/O handling. This is
delegated to an ``IOManager`` class, of which there are currently
three implementations:

* ``EpollIOManager`` in ``_io_epoll.py`` (used on Linux, illumos)

* ``KqueueIOManager`` in ``_io_kqueue.py`` (used on macOS, \*BSD)

* ``WindowsIOManager`` in ``_io_windows.py`` (used on Windows)

The epoll and kqueue backends take advantage of the epoll and kqueue
wrappers in the stdlib :mod:`select` module. The windows backend uses
CFFI to access to the Win32 API directly (see
``trio/_core/_windows_cffi.py``). In general, we prefer to go directly
to the raw OS functionality rather than use :mod:`selectors`, for
several reasons:

* Controlling our own fate: I/O handling is pretty core to what Trio
  is about, and :mod:`selectors` is (as of 2017-03-01) somewhat buggy
  (e.g. `issue 29256 <https://bugs.python.org/issue29256>`__, `issue
  29255 <https://bugs.python.org/issue29255>`__). Which isn't a big
  deal on its own, but since :mod:`selectors` is part of the standard
  library we can't fix it and ship an updated version; we're stuck
  with whatever we get. We want more control over our users'
  experience than that.

* Impedence mismatch: the :mod:`selectors` API isn't particularly
  well-fitted to how we want to use it. For example, kqueue natively
  treats an interest in readability of some fd as a separate thing
  from an interest in that same fd's writability, which neatly matches
  Trio's model. :class:`selectors.KqueueSelector` goes to some effort
  internally to lump together all interests in a single fd, and to use
  it we'd then we'd have to jump through more hoops to reverse
  this. Of course, the native epoll API is fd-centric in the same way
  as the :mod:`selectors` API so we do still have to write code to
  jump through these hoops, but the point is that the :mod:`selectors`
  abstractions aren't providing a lot of extra value.

* (Most important) Access to raw platform capabilities:
  :mod:`selectors` is highly inadequate on Windows, and even on
  Unix-like systems it hides a lot of power (e.g. kqueue can do a lot
  more than just check fd readability/writability!).

The ``IOManager`` layer provides a fairly raw exposure of the capabilities
of each system, with public API functions that vary between different
backends. (This is somewhat inspired by how :mod:`os` works.) These
public APIs are then exported as part of :mod:`trio.lowlevel`, and
higher-level APIs like :mod:`trio.socket` abstract over these
system-specific APIs to provide a uniform experience.

Currently the choice of backend is made statically at import time, and
there is no provision for "pluggable" backends. The intuition here is
that we'd rather focus our energy on making one set of solid, official
backends that provide a high-quality experience out-of-the-box on all
supported systems.
