Tutorial
========

.. The Trio tutorial

   the spiel about what a concurrent library is

   Traditionally Python is a synchronous language, and we assume
   you're familiar with that kind of programming, but don't assume any
   knowledge of concurrent programming. (And even if you are familiar
   with concurrent programming using another library like Twisted or
   asyncio, or another language like Go or Erlang, then you should
   still probably read this, because Trio is different.)

   Trio turns Python into a concurrent language. It takes the core
   async/await syntax introduced in 3.5, and uses it to add three
   new pieces of semantics:

   - cancel scopes: a generic system for managing timeouts and
     cancellation
   - nurseries: which let your program do multiple things at the same
     time
   - MultiErrors: for when multiple things go wrong at once

   Of course it also provides a complete suite of APIs for doing
   networking, file I/O, using worker threads,

   We'll go through and explain each of these

   simple cancellation
   applied to an HTTP request
     with fail_after(5):
         response = await asks.get("https://httpbin.org/delay/1")
         print(response)
   and then again with /delay/10

   (note that asks needs cpython 3.6 though. maybe just for one async
   generator?)

   value of async/await: show you where the cancellation exceptions
   can happen -- see pillar re: explicit cancel points

   (also briefly discuss cancel scopes and cancel() + the query APIs,
   fail_after vs move_on_after, current_time() and
   current_effective_deadline())

   simple multi-task concurrency
   applied to do multiple HTTP requests
   adding a per-request timeout
   adding a timeout on the whole thing -- demonstrating wrapping
       cancel around a nursery

   pillars: implicit concurrency and exception raising
   and explicit schedule points

   example: the scheduling trace

   implicit concurrency -> use echo example to introduce networking
   API, and show how to do explicit concurrency
   and demonstrate start()
   then point out that you can just use serve_tcp()

   exceptions and MultiError

   example: catch-all logging in our echo server

   review of the three (or four) core language extensions
   and how they fit together and

.. currentmodule:: trio

Welcome to the Trio tutorial! Trio is a modern Python library for
writing asynchronous applications – that is, programs that want to do
multiple things at the same time with parallelized I/O, like a web
spider that fetches lots of pages in parallel, a web server juggling
lots of simultaneous downloads... that sort of thing. Here we'll try
to give a gentle introduction to asynchronous programming with Trio.

We assume that you're familiar with Python in general, but don't worry
– we don't assume you know anything about asynchronous programming or
Python's new ``async/await`` feature.

Also, unlike many ``async/await`` tutorials, we assume that your goal
is to *use* Trio to write interesting programs, so we won't go into
the nitty-gritty details of how ``async/await`` is implemented inside
the Python interpreter. The word "coroutine" is never mentioned. The
fact is, you really don't *need* to know any of that stuff unless you
want to *implement* a library like Trio, so we leave it out (though
we'll throw in a few links for those who want to dig deeper).

Okay, ready? Let's get started.


Before you begin
----------------

1. Make sure you're using Python 3.6 or newer.

2. ``python3 -m pip install --upgrade trio`` (or on Windows, maybe
   ``py -3 -m pip install --upgrade trio`` – `details
   <https://packaging.python.org/installing/>`__)

3. Can you ``import trio``? If so then you're good to go!


If you get lost or confused...
------------------------------

...then we want to know! We have a friendly `chat channel
<https://gitter.im/python-trio/general>`__, you can ask questions
`using the "python-trio" tag on StackOverflow
<https://stackoverflow.com/questions/ask?tags=python+python-trio>`__, or just
`file a bug <https://github.com/python-trio/trio/issues/new>`__ (if
our documentation is confusing, that's our fault, and we want to fix
it!).


Async functions
---------------

Python 3.5 added a major new feature: async functions. Using Trio is
all about writing async functions, so let's start there.

An async function is defined like a normal function, except you write
``async def`` instead of ``def``::

   # A regular function
   def regular_double(x):
       return 2 * x

   # An async function
   async def async_double(x):
       return 2 * x

"Async" is short for "asynchronous"; we'll sometimes refer to regular
functions like ``regular_double`` as "synchronous functions", to
distinguish them from async functions.

From a user's point of view, there are two differences between an
async function and a regular function:

1. To call an async function, you have to use the ``await``
   keyword. So instead of writing ``regular_double(3)``, you write
   ``await async_double(3)``.

2. You can't use the ``await`` keyword inside the body of a regular
   function. If you try it, you'll get a syntax error::

      def print_double(x):
          print(await async_double(x))   # <-- SyntaxError here

   But inside an async function, ``await`` is allowed::

      async def print_double(x):
          print(await async_double(x))   # <-- OK!

Now, let's think about the consequences here: if you need ``await`` to
call an async function, and only async functions can use
``await``... here's a little table:

=======================  ==================================  ===================
If a function like this  wants to call a function like this  is it gonna happen?
=======================  ==================================  ===================
sync                     sync                                ✓
sync                     async                               **NOPE**
async                    sync                                ✓
async                    async                               ✓
=======================  ==================================  ===================

So in summary: As a user, the entire advantage of async functions over
regular functions is that async functions have a superpower: they can
call other async functions.

This immediately raises two questions: how, and why? Specifically:

When your Python program starts up, it's running regular old sync
code. So there's a chicken-and-the-egg problem: once we're running an
async function we can call other async functions, but *how* do we call
that first async function?

And, if the only reason to write an async function is that it can call
other async functions, *why* on earth would we ever use them in
the first place? I mean, as superpowers go this seems a bit
pointless. Wouldn't it be simpler to just... not use any async
functions at all?

This is where an async library like Trio comes in. It provides two
things:

1. A runner function, which is a special *synchronous* function that
   takes and calls an *asynchronous* function. In Trio, this is
   ``trio.run``::

      import trio

      async def async_double(x):
          return 2 * x

      trio.run(async_double, 3)  # returns 6

   So that answers the "how" part.

2. A bunch of useful async functions – in particular, functions for
   doing I/O. So that answers the "why": these functions are async,
   and they're useful, so if you want to use them, you have to write
   async code. If you think keeping track of these ``async`` and
   ``await`` things is annoying, then too bad – you've got no choice
   in the matter! (Well, OK, you could just not use Trio. That's a
   legitimate option. But it turns out that the ``async/await`` stuff
   is actually a good thing, for reasons we'll discuss a little bit
   later.)

   Here's an example function that uses
   :func:`trio.sleep`. (:func:`trio.sleep` is like :func:`time.sleep`,
   but with more async.)

   .. code-block:: python3

      import trio

      async def double_sleep(x):
          await trio.sleep(2 * x)

      trio.run(double_sleep, 3)  # does nothing for 6 seconds then returns

.. _async-sandwich:

So it turns out our ``async_double`` function is actually a bad
example. I mean, it works, it's fine, there's nothing *wrong* with it,
but it's pointless: it could just as easily be written as a regular
function, and it would be more useful that way. ``double_sleep`` is a
much more typical example: we have to make it async, because it calls
another async function. The end result is a kind of async sandwich,
with Trio on both sides and our code in the middle:

.. code-block:: none

  trio.run -> double_sleep -> trio.sleep

This "sandwich" structure is typical for async code; in general, it
looks like:

.. code-block:: none

  trio.run -> [async function] -> ... -> [async function] -> trio.whatever

It's exactly the functions on the path between :func:`trio.run` and
``trio.whatever`` that have to be async. Trio provides the async
bread, and then your code makes up the async sandwich's tasty async
filling. Other functions (e.g., helpers you call along the way) should
generally be regular, non-async functions.


Warning: don't forget that ``await``!
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Now would be a good time to open up a Python prompt and experiment a
little with writing simple async functions and running them with
``trio.run``.

At some point in this process, you'll probably write some code like
this, that tries to call an async function but leaves out the
``await``::

   import time
   import trio

   async def broken_double_sleep(x):
       print("*yawn* Going to sleep")
       start_time = time.perf_counter()

       # Whoops, we forgot the 'await'!
       trio.sleep(2 * x)

       sleep_time = time.perf_counter() - start_time
       print("Woke up after {:.2f} seconds, feeling well rested!".format(sleep_time))

   trio.run(broken_double_sleep, 3)

You might think that Python would raise an error here, like it does
for other kinds of mistakes we sometimes make when calling a
function. Like, if we forgot to pass :func:`trio.sleep` its required
argument, then we would get a nice :exc:`TypeError` saying so. But
unfortunately, if you forget an ``await``, you don't get that. What
you actually get is:

.. code-block:: none

   >>> trio.run(broken_double_sleep, 3)
   *yawn* Going to sleep
   Woke up after 0.00 seconds, feeling well rested!
   __main__:4: RuntimeWarning: coroutine 'sleep' was never awaited
   >>>

This is clearly broken – 0.00 seconds is not long enough to feel well
rested! Yet the code acts like it succeeded – no exception was
raised. The only clue that something went wrong is that it prints
``RuntimeWarning: coroutine 'sleep' was never awaited``. Also, the
exact place where the warning is printed might vary, because it
depends on the whims of the garbage collector. If you're using PyPy,
you might not even get a warning at all until the next GC collection
runs:

.. code-block:: none

   # On PyPy:
   >>>> trio.run(broken_double_sleep, 3)
   *yawn* Going to sleep
   Woke up after 0.00 seconds, feeling well rested!
   >>>> # what the ... ?? not even a warning!

   >>>> # but forcing a garbage collection gives us a warning:
   >>>> import gc
   >>>> gc.collect()
   /home/njs/pypy-3.8-nightly/lib-python/3/importlib/_bootstrap.py:191: RuntimeWarning: coroutine 'sleep' was never awaited
   if _module_locks.get(name) is wr:    # XXX PyPy fix?
   0
   >>>>

(If you can't see the warning above, try scrolling right.)

Forgetting an ``await`` like this is an *incredibly common
mistake*. You will mess this up. Everyone does. And Python will not
help you as much as you'd hope 😞. The key thing to remember is: if
you see the magic words ``RuntimeWarning: coroutine '...' was never
awaited``, then this *always* means that you made the mistake of
leaving out an ``await`` somewhere, and you should ignore all the
other error messages you see and go fix that first, because there's a
good chance the other stuff is just collateral damage. I'm not even
sure what all that other junk in the PyPy output is. Fortunately I
don't need to know, I just need to fix my function!

("I thought you said you weren't going to mention coroutines!" Yes,
well, *I* didn't mention coroutines, Python did. Take it up with
Guido! But seriously, this is unfortunately a place where the internal
implementation details do leak out a bit.)

Why does this happen? In Trio, every time we use ``await`` it's to
call an async function, and every time we call an async function we
use ``await``. But Python's trying to keep its options open for other
libraries that are *ahem* a little less organized about things. So
while for our purposes we can think of ``await trio.sleep(...)`` as a
single piece of syntax, Python thinks of it as two things: first a
function call that returns this weird "coroutine" object::

   >>> trio.sleep(3)
   <coroutine object sleep at 0x7f5ac77be6d0>

and then that object gets passed to ``await``, which actually runs the
function. So if you forget ``await``, then two bad things happen: your
function doesn't actually get called, and you get a "coroutine" object
where you might have been expecting something else, like a number::

   >>> async_double(3) + 1
   TypeError: unsupported operand type(s) for +: 'coroutine' and 'int'

If you didn't already mess this up naturally, then give it a try on
purpose: try writing some code with a missing ``await``, or an extra
``await``, and see what you get. This way you'll be prepared for when
it happens to you for real.

And remember: watch out for ``RuntimeWarning: coroutine '...' was
never awaited``; it means you need to find and fix your missing
``await``.


Okay, let's see something cool already
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

So now we've started using Trio, but so far all we've learned to do is
write functions that print things and sleep for various lengths of
time. Interesting enough, but we could just as easily have done that
with :func:`time.sleep`. ``async/await`` is useless!

Well, not really. Trio has one more trick up its sleeve, that makes
async functions more powerful than regular functions: it can run
multiple async functions *at the same time*. Here's an example:

.. _tutorial-example-tasks-intro:

.. literalinclude:: tutorial/tasks-intro.py
   :linenos:

There's a lot going on in here, so we'll take it one step at a
time. In the first part, we define two async functions ``child1`` and
``child2``. These should look familiar from the last section:

.. literalinclude:: tutorial/tasks-intro.py
   :linenos:
   :lineno-match:
   :start-at: async def child1
   :end-at: child2: exiting

Next, we define ``parent`` as an async function that's going to call
``child1`` and ``child2`` concurrently:

.. literalinclude:: tutorial/tasks-intro.py
   :linenos:
   :lineno-match:
   :start-at: async def parent
   :end-at: all done!

It does this by using a mysterious ``async with`` statement to create
a "nursery", and then "spawns" ``child1`` and ``child2`` into the
nursery.

Let's start with this ``async with`` thing. It's actually pretty
simple. In regular Python, a statement like ``with someobj: ...``
instructs the interpreter to call ``someobj.__enter__()`` at the
beginning of the block, and to call ``someobj.__exit__()`` at the end
of the block. We call ``someobj`` a "context manager". An ``async
with`` does exactly the same thing, except that where a regular
``with`` statement calls regular methods, an ``async with`` statement
calls async methods: at the start of the block it does ``await
someobj.__aenter__()`` and at that end of the block it does ``await
someobj.__aexit__()``. In this case we call ``someobj`` an "async
context manager". So in short: ``with`` blocks are a shorthand for
calling some functions, and since with async/await Python now has two
kinds of functions, it also needs two kinds of ``with`` blocks. That's
all there is to it! If you understand async functions, then you
understand ``async with``.

.. note::

   This example doesn't use them, but while we're here we might as
   well mention the one other piece of new syntax that async/await
   added: ``async for``. It's basically the same idea as ``async
   with`` versus ``with``: An ``async for`` loop is just like a
   ``for`` loop, except that where a ``for`` loop does
   ``iterator.__next__()`` to fetch the next item, an ``async for``
   does ``await async_iterator.__anext__()``. Now you understand all
   of async/await. Basically just remember that it involves making
   sandwiches and sticking the word "async" in front of everything,
   and you'll do fine.

Now that we understand ``async with``, let's look at ``parent`` again:

.. literalinclude:: tutorial/tasks-intro.py
   :linenos:
   :lineno-match:
   :start-at: async def parent
   :end-at: all done!

There are only 4 lines of code that really do anything here. On line
17, we use :func:`trio.open_nursery` to get a "nursery" object, and
then inside the ``async with`` block we call ``nursery.start_soon`` twice,
on lines 19 and 22. There are actually two ways to call an async
function: the first one is the one we already saw, using ``await
async_fn()``; the new one is ``nursery.start_soon(async_fn)``: it asks Trio
to start running this async function, *but then returns immediately
without waiting for the function to finish*. So after our two calls to
``nursery.start_soon``, ``child1`` and ``child2`` are now running in the
background. And then at line 25, the commented line, we hit the end of
the ``async with`` block, and the nursery's ``__aexit__`` function
runs. What this does is force ``parent`` to stop here and wait for all
the children in the nursery to exit. This is why you have to use
``async with`` to get a nursery: it gives us a way to make sure that
the child calls can't run away and get lost. One reason this is
important is that if there's a bug or other problem in one of the
children, and it raises an exception, then it lets us propagate that
exception into the parent; in many other frameworks, exceptions like
this are just discarded. Trio never discards exceptions.

Ok! Let's try running it and see what we get:

.. code-block:: none

   parent: started!
   parent: spawning child1...
   parent: spawning child2...
   parent: waiting for children to finish...
     child2: started! sleeping now...
     child1: started! sleeping now...
       [... 1 second passes ...]
     child1: exiting!
     child2: exiting!
   parent: all done!

(Your output might have the order of the "started" and/or "exiting"
lines swapped compared to mine.)

Notice that ``child1`` and ``child2`` both start together and then
both exit together. And, even though we made two calls to
``trio.sleep(1)``, the program finished in just one second total.
So it looks like ``child1`` and ``child2`` really are running at the
same time!

Now, if you're familiar with programming using threads, this might
look familiar – and that's intentional. But it's important to realize
that *there are no threads here*. All of this is happening in a single
thread. To remind ourselves of this, we use slightly different
terminology: instead of spawning two "threads", we say that we spawned
two "tasks". There are two differences between tasks and threads: (1)
many tasks can take turns running on a single thread, and (2) with
threads, the Python interpreter/operating system can switch which
thread is running whenever they feel like it; with tasks, we can only
switch at certain designated places we call :ref:`"checkpoints"
<checkpoints>`. In the next section, we'll dig into what this means.


.. _tutorial-instrument-example:

Task switching illustrated
~~~~~~~~~~~~~~~~~~~~~~~~~~

The big idea behind async/await-based libraries like Trio is to run
lots of tasks simultaneously on a single thread by switching between
them at appropriate places – so for example, if we're implementing a
web server, then one task could be sending an HTTP response at the
same time as another task is waiting for new connections. If all you
want to do is use Trio, then you don't need to understand all the
nitty-gritty detail of how this switching works – but it's very useful
to have at least a general intuition about what Trio is doing "under
the hood" when your code is executing. To help build that intuition,
let's look more closely at how Trio ran our example from the last
section.

Fortunately, Trio provides a :ref:`rich set of tools for inspecting
and debugging your programs <instrumentation>`. Here we want to watch
:func:`trio.run` at work, which we can do by writing a class we'll
call ``Tracer``, which implements Trio's :class:`~trio.abc.Instrument`
interface. Its job is to log various events as they happen:

.. literalinclude:: tutorial/tasks-with-trace.py
   :pyobject: Tracer

Then we re-run our example program from the previous section, but this
time we pass :func:`trio.run` a ``Tracer`` object:

.. literalinclude:: tutorial/tasks-with-trace.py
   :start-at: trio.run

This generates a *lot* of output, so we'll go through it one step at a
time.

First, there's a bit of chatter while Trio gets ready to run our
code. Most of this is irrelevant to us for now, but in the middle you
can see that Trio has created a task for the ``__main__.parent``
function, and "scheduled" it (i.e., made a note that it should be run
soon):

.. code-block:: none

   $ python3 tutorial/tasks-with-trace.py
   !!! run started
   ### new task spawned: <init>
   ### task scheduled: <init>
   ### doing a quick check for I/O
   ### finished I/O check (took 1.1122087016701698e-05 seconds)
   >>> about to run one step of task: <init>
   ### new task spawned: <call soon task>
   ### task scheduled: <call soon task>
   ### new task spawned: __main__.parent
   ### task scheduled: __main__.parent
   <<< task step finished: <init>
   ### doing a quick check for I/O
   ### finished I/O check (took 6.4980704337358475e-06 seconds)

Once the initial housekeeping is done, Trio starts running the
``parent`` function, and you can see ``parent`` creating the two child
tasks. Then it hits the end of the ``async with`` block, and pauses:

.. code-block:: none

   >>> about to run one step of task: __main__.parent
   parent: started!
   parent: spawning child1...
   ### new task spawned: __main__.child1
   ### task scheduled: __main__.child1
   parent: spawning child2...
   ### new task spawned: __main__.child2
   ### task scheduled: __main__.child2
   parent: waiting for children to finish...
   <<< task step finished: __main__.parent

Control then goes back to :func:`trio.run`, which logs a bit more
internal chatter:

.. code-block:: none

   >>> about to run one step of task: <call soon task>
   <<< task step finished: <call soon task>
   ### doing a quick check for I/O
   ### finished I/O check (took 5.476875230669975e-06 seconds)

And then gives the two child tasks a chance to run:

.. code-block:: none

   >>> about to run one step of task: __main__.child2
     child2 started! sleeping now...
   <<< task step finished: __main__.child2

   >>> about to run one step of task: __main__.child1
     child1: started! sleeping now...
   <<< task step finished: __main__.child1

Each task runs until it hits the call to :func:`trio.sleep`, and then
suddenly we're back in :func:`trio.run` deciding what to run next. How
does this happen? The secret is that :func:`trio.run` and
:func:`trio.sleep` work together to make it happen: :func:`trio.sleep`
has access to some special magic that lets it pause its entire
call stack, so it sends a note to :func:`trio.run` requesting to be
woken again after 1 second, and then suspends the task. And once the
task is suspended, Python gives control back to :func:`trio.run`,
which decides what to do next. (If this sounds similar to the way that
generators can suspend execution by doing a ``yield``, then that's not
a coincidence: inside the Python interpreter, there's a lot of overlap
between the implementation of generators and async functions.)

.. note::

   You might wonder whether you can mix-and-match primitives from
   different async libraries. For example, could we use
   :func:`trio.run` together with :func:`asyncio.sleep`? The answer is
   no, we can't, and the paragraph above explains why: the two sides
   of our async sandwich have a private language they use to talk to
   each other, and different libraries use different languages. So if
   you try to call :func:`asyncio.sleep` from inside a
   :func:`trio.run`, then Trio will get very confused indeed and
   probably blow up in some dramatic way.

Only async functions have access to the special magic for suspending a
task, so only async functions can cause the program to switch to a
different task. What this means if a call *doesn't* have an ``await``
on it, then you know that it *can't* be a place where your task will
be suspended. This makes tasks much `easier to reason about
<https://glyph.twistedmatrix.com/2014/02/unyielding.html>`__ than
threads, because there are far fewer ways that tasks can be
interleaved with each other and stomp on each others' state. (For
example, in Trio a statement like ``a += 1`` is always atomic – even
if ``a`` is some arbitrarily complicated custom object!) Trio also
makes some :ref:`further guarantees beyond that <checkpoints>`, but
that's the big one.

And now you also know why ``parent`` had to use an ``async with`` to
open the nursery: if we had used a regular ``with`` block, then it
wouldn't have been able to pause at the end and wait for the children
to finish; we need our cleanup function to be async, which is exactly
what ``async with`` gives us.

Now, back to our execution trace. To recap: at this point ``parent``
is waiting on ``child1`` and ``child2``, and both children are
sleeping. So :func:`trio.run` checks its notes, and sees that there's
nothing to be done until those sleeps finish – unless possibly some
external I/O event comes in. If that happened, then it might give us
something to do. Of course we aren't doing any I/O here so it won't
happen, but in other situations it could. So next it calls an
operating system primitive to put the whole process to sleep:

.. code-block:: none

   ### waiting for I/O for up to 0.9999009938910604 seconds

And in fact no I/O does arrive, so one second later we wake up again,
and Trio checks its notes again. At this point it checks the current
time, compares it to the notes that :func:`trio.sleep` sent saying
when the two child tasks should be woken up again, and realizes
that they've slept for long enough, so it schedules them to run soon:

.. code-block:: none

   ### finished I/O check (took 1.0006483688484877 seconds)
   ### task scheduled: __main__.child1
   ### task scheduled: __main__.child2

And then the children get to run, and this time they run to
completion. Remember how ``parent`` is waiting for them to finish?
Notice how ``parent`` gets scheduled when the first child exits:

.. code-block:: none

   >>> about to run one step of task: __main__.child1
     child1: exiting!
   ### task scheduled: __main__.parent
   ### task exited: __main__.child1
   <<< task step finished: __main__.child1

   >>> about to run one step of task: __main__.child2
     child2 exiting!
   ### task exited: __main__.child2
   <<< task step finished: __main__.child2

Then, after another check for I/O, ``parent`` wakes up. The nursery
cleanup code notices that all its children have exited, and lets the
nursery block finish. And then ``parent`` makes a final print and
exits:

.. code-block:: none

   ### doing a quick check for I/O
   ### finished I/O check (took 9.045004844665527e-06 seconds)

   >>> about to run one step of task: __main__.parent
   parent: all done!
   ### task scheduled: <init>
   ### task exited: __main__.parent
   <<< task step finished: __main__.parent

And finally, after a bit more internal bookkeeping, :func:`trio.run`
exits too:

.. code-block:: none

   ### doing a quick check for I/O
   ### finished I/O check (took 5.996786057949066e-06 seconds)
   >>> about to run one step of task: <init>
   ### task scheduled: <call soon task>
   ### task scheduled: <init>
   <<< task step finished: <init>
   ### doing a quick check for I/O
   ### finished I/O check (took 6.258022040128708e-06 seconds)
   >>> about to run one step of task: <call soon task>
   ### task exited: <call soon task>
   <<< task step finished: <call soon task>
   >>> about to run one step of task: <init>
   ### task exited: <init>
   <<< task step finished: <init>
   !!! run finished

You made it!

That was a lot of text, but again, you don't need to understand
everything here to use Trio – in fact, Trio goes to great lengths to
make each task feel like it executes in a simple, linear way. (Just
like your operating system goes to great lengths to make it feel like
your single-threaded code executes in a simple linear way, even though
under the covers the operating system juggles between different
threads and processes in essentially the same way Trio does.) But it
is useful to have a rough model in your head of how the code you write
is actually executed, and – most importantly – the consequences of
that for parallelism.

Alternatively, if this has just whetted your appetite and you want to
know more about how ``async/await`` works internally, then `this blog
post
<https://snarky.ca/how-the-heck-does-async-await-work-in-python-3-5/>`__
is a good deep dive, or check out `this great walkthrough
<https://github.com/AndreLouisCaron/a-tale-of-event-loops>`__ to see
how to build a simple async I/O framework from the ground up.


A kinder, gentler GIL
---------------------

Speaking of parallelism – let's zoom out for a moment and talk about
how async/await compares to other ways of handling concurrency in
Python.

As we've already noted, Trio tasks are conceptually rather similar to
Python's built-in threads, as provided by the :mod:`threading`
module. And in all common Python implementations, threads have a
famous limitation: the Global Interpreter Lock, or "GIL" for
short. The GIL means that even if you use multiple threads, your code
still (mostly) ends up running on a single core. People tend to find
this frustrating.

But from Trio's point of view, the problem with the GIL isn't that it
restricts parallelism. Of course it would be nice if Python had better
options for taking advantage of multiple cores, but that's an
extremely difficult problem to solve, and in the meantime there are
lots of problems where a single core is totally adequate – or where if
it isn't, then process-level or machine-level parallelism works fine.

No, the problem with the GIL is that it's a *lousy deal*: we give up
on using multiple cores, and in exchange we get... almost all the same
challenges and mind-bending bugs that come with real parallel
programming, and – to add insult to injury – `pretty poor scalability
<https://twitter.com/hynek/status/771790449057132544>`__. Threads in
Python just aren't that appealing.

Trio doesn't make your code run on multiple cores; in fact, as we saw
above, it's baked into Trio's design that when it has multiple tasks,
they take turns, so at each moment only one of them is actively running.
We're not so much overcoming the GIL as embracing it. But if you're
willing to accept that, plus a bit of extra work to put these new
``async`` and ``await`` keywords in the right places, then in exchange 
you get:

* Excellent scalability: Trio can run 10,000+ tasks simultaneously
  without breaking a sweat, so long as their total CPU demands don't
  exceed what a single core can provide. (This is common in, for
  example, network servers that have lots of clients connected, but
  only a few active at any given time.)

* Fancy features: most threading systems are implemented in C and
  restricted to whatever features the operating system provides. In
  Trio our logic is all in Python, which makes it possible to
  implement powerful and ergonomic features like :ref:`Trio's
  cancellation system <cancellation>`.

* Code that's easier to reason about: the ``await`` keyword means that
  potential task-switching points are explicitly marked within each
  function. This can make Trio code `dramatically easier to reason
  about <https://glyph.twistedmatrix.com/2014/02/unyielding.html>`__
  than the equivalent program using threads.

Certainly it's not appropriate for every app... but there are a lot of
situations where the trade-offs here look pretty appealing.

There is one downside that's important to keep in mind, though. Making
checkpoints explicit gives you more control over how your tasks can be
interleaved – but with great power comes great responsibility. With
threads, the runtime environment is responsible for making sure that
each thread gets its fair share of running time. With Trio, if some
task runs off and does stuff for seconds on end without executing a
checkpoint, then... all your other tasks will just have to wait.

Here's an example of how this can go wrong. Take our :ref:`example
from above <tutorial-example-tasks-intro>`, and replace the calls to
:func:`trio.sleep` with calls to :func:`time.sleep`. If we run our
modified program, we'll see something like:

.. code-block:: none

   parent: started!
   parent: spawning child1...
   parent: spawning child2...
   parent: waiting for children to finish...
     child2 started! sleeping now...
       [... pauses for 1 second ...]
     child2 exiting!
     child1: started! sleeping now...
       [... pauses for 1 second ...]
     child1: exiting!
   parent: all done!

One of the major reasons why Trio has such a rich
:ref:`instrumentation API <tutorial-instrument-example>` is to make it
possible to write debugging tools to catch issues like this.


Networking with Trio
--------------------

Now let's take what we've learned and use it to do some I/O, which is
where async/await really shines.


An echo client
~~~~~~~~~~~~~~

The traditional application for demonstrating network APIs is an "echo
server": a program that accepts arbitrary data from a client, and then
sends that same data right back. (Probably a more relevant example
these days would be an application that does lots of concurrent HTTP
requests, but for that `you need an HTTP library
<https://github.com/python-trio/trio/issues/236#issuecomment-310784001>`__
such as `asks <https://asks.readthedocs.io>`__, so we'll stick
with the echo server tradition.)

To start with, here's an example echo *client*, i.e., the program that
will send some data at our echo server and get responses back:

.. _tutorial-echo-client-example:

.. literalinclude:: tutorial/echo-client.py
   :linenos:

The overall structure here should be familiar, because it's just like
our :ref:`last example <tutorial-example-tasks-intro>`: we have a
parent task, which spawns two child tasks to do the actual work, and
then at the end of the ``async with`` block it switches into full-time
parenting mode while waiting for them to finish. But now instead of
just calling :func:`trio.sleep`, the children use some of Trio's
networking APIs.

Let's look at the parent first:

.. literalinclude:: tutorial/echo-client.py
   :linenos:
   :lineno-match:
   :pyobject: parent

First we call :func:`trio.open_tcp_stream` to make a TCP connection to
the server. ``127.0.0.1`` is a magic `IP address
<https://en.wikipedia.org/wiki/IP_address>`__ meaning "the computer
I'm running on", so this connects us to whatever program on the local
computer is using ``PORT`` as its contact point. This function returns
an object implementing Trio's :class:`~trio.abc.Stream` interface,
which gives us methods to send and receive bytes, and to close the
connection when we're done. We use an ``async with`` block to make
sure that we do close the connection – not a big deal in a toy example
like this, but it's a good habit to get into, and Trio is designed to
make ``with`` and ``async with`` blocks easy to use.

Finally, we start up two child tasks, and pass each of them a
reference to the stream. (This is also a good example of how
``nursery.start_soon`` lets you pass positional arguments to the
spawned function.)

Our first task's job is to send data to the server:

.. literalinclude:: tutorial/echo-client.py
   :linenos:
   :lineno-match:
   :pyobject: sender

It uses a loop that alternates between calling ``await
client_stream.send_all(...)`` to send some data (this is the method
you use for sending data on any kind of Trio stream), and then
sleeping for a second to avoid making the output scroll by too fast on
your terminal.

And the second task's job is to process the data the server sends back:

.. literalinclude:: tutorial/echo-client.py
   :linenos:
   :lineno-match:
   :pyobject: receiver

It uses an ``async for`` loop to fetch data from the server.
Alternatively, it could use `~trio.abc.ReceiveStream.receive_some`,
which is the opposite of `~trio.abc.SendStream.send_all`, but using
``async for`` saves some boilerplate.

And now we're ready to look at the server.


.. _tutorial-echo-server-example:

An echo server
~~~~~~~~~~~~~~

As usual, let's look at the whole thing first, and then we'll discuss
the pieces:

.. literalinclude:: tutorial/echo-server.py
   :linenos:

Let's start with ``main``, which is just one line long:

.. literalinclude:: tutorial/echo-server.py
   :linenos:
   :lineno-match:
   :pyobject: main

What this does is call :func:`serve_tcp`, which is a convenience
function Trio provides that runs forever (or at least until you hit
control-C or otherwise cancel it). This function does several helpful
things:

* It creates a nursery internally, so that our server will be able to
  handle multiple connections at the same time.

* It listens for incoming TCP connections on the specified ``PORT``.

* Whenever a connection arrives, it starts a new task running the
  function we pass (in this example it's ``echo_server``), and passes
  it a stream representing that connection.

* When each task exits, it makes sure to close the corresponding
  connection. (That's why you don't see any ``async with
  server_stream`` in the server – :func:`serve_tcp` takes care of this
  for us.)

So :func:`serve_tcp` is pretty handy! This part works pretty much the
same for any server, whether it's an echo server, HTTP server, SSH
server, or whatever, so it makes sense to bundle it all up together in
a helper function like this.

Now let's look at ``echo_server``, which handles each client
connection – so if there are multiple clients, there might be multiple
calls to ``echo_server`` running at the same time. This is where we
implement our server's "echo" behavior. This should be pretty
straightforward to understand, because it uses the same stream
functions we saw in the last section:

.. literalinclude:: tutorial/echo-server.py
   :linenos:
   :lineno-match:
   :pyobject: echo_server

The argument ``server_stream`` is provided by :func:`serve_tcp`, and
is the other end of the connection we made in the client: so the data
that the client passes to ``send_all`` will come out here. Then we
have a ``try`` block discussed below, and finally the server loop
which alternates between reading some data from the socket and then
sending it back out again (unless the socket was closed, in which case
we quit).

So what's that ``try`` block for? Remember that in Trio, like Python
in general, exceptions keep propagating until they're caught. Here we
think it's plausible there might be unexpected exceptions, and we want
to isolate that to making just this one task crash, without taking
down the whole program. For example, if the client closes the
connection at the wrong moment then it's possible this code will end
up calling ``send_all`` on a closed connection and get a
:exc:`BrokenResourceError`; that's unfortunate, and in a more serious
program we might want to handle it more explicitly, but it doesn't
indicate a problem for any *other* connections. On the other hand, if
the exception is something like a :exc:`KeyboardInterrupt`, we *do*
want that to propagate out into the parent task and cause the whole
program to exit. To express this, we use a ``try`` block with an
``except Exception:`` handler.

In general, Trio leaves it up to you to decide whether and how you
want to handle exceptions, just like Python in general.


Try it out
~~~~~~~~~~

Open a few terminals, run ``echo-server.py`` in one, run
``echo-client.py`` in another, and watch the messages scroll by! When
you get bored, you can exit by hitting control-C.

Some things to try:

* Open several terminals, and run multiple clients at the same time,
  all talking to the same server.

* See how the server reacts when you hit control-C on the client.

* See how the client reacts when you hit control-C on the server.


Flow control in our echo client and server
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Here's a question you might be wondering about: why does our client
use two separate tasks for sending and receiving, instead of a single
task that alternates between them – like the server has? For example,
our client could use a single task like::

   # Can you spot the two problems with this code?
   async def send_and_receive(client_stream):
       while True:
           data = ...
           await client_stream.send_all(data)
           received = await client_stream.receive_some()
           if not received:
               sys.exit()
           await trio.sleep(1)

It turns out there are two problems with this – one minor and one
major. Both relate to flow control. The minor problem is that when we
call ``receive_some`` here we're not waiting for *all* the data to be
available; ``receive_some`` returns as soon as *any* data is available. If
``data`` is small, then our operating systems / network / server will
*probably* keep it all together in a single chunk, but there's no
guarantee. If the server sends ``hello`` then we might get ``hello``,
or ``hel`` ``lo``, or ``h`` ``e`` ``l`` ``l`` ``o``, or ... bottom
line, any time we're expecting more than one byte of data, we have to
be prepared to call ``receive_some`` multiple times.

And where this would go especially wrong is if we find ourselves in
the situation where ``data`` is big enough that it passes some
internal threshold, and the operating system or network decide to
always break it up into multiple pieces. Now on each pass through the
loop, we send ``len(data)`` bytes, but read less than that. The result
is something like a memory leak: we'll end up with more and more data
backed up in the network, until eventually something breaks.

.. note:: If you're curious *how* things break, then you can use
   `~trio.abc.ReceiveStream.receive_some`\'s optional argument to put
   a limit on how many bytes you read each time, and see what happens.

We could fix this by keeping track of how much data we're expecting at
each moment, and then keep calling ``receive_some`` until we get it all::

   expected = len(data)
   while expected > 0:
       received = await client_stream.receive_some(expected)
       if not received:
           sys.exit(1)
       expected -= len(received)

This is a bit cumbersome, but it would solve this problem.

There's another problem, though, that's deeper. We're still
alternating between sending and receiving. Notice that when we send
data, we use ``await``: this means that sending can potentially
*block*. Why does this happen? Any data that we send goes first into
an operating system buffer, and from there onto the network, and then
another operating system buffer on the receiving computer, before the
receiving program finally calls ``receive_some`` to take the data out
of these buffers. If we call ``send_all`` with a small amount of data,
then it goes into these buffers and ``send_all`` returns immediately.
But if we send enough data fast enough, eventually the buffers fill
up, and ``send_all`` will block until the remote side calls
``receive_some`` and frees up some space.

Now let's think about this from the server's point of view. Each time
it calls ``receive_some``, it gets some data that it needs to send
back. And until it sends it back, the data is sitting around takes up
memory. Computers have finite amounts of RAM, so if our server is well
behaved then at some point it needs to stop calling ``receive_some``
until it gets rid of some of the old data by doing its own call to
``send_all``. So for the server, really the only viable option is to
alternate between receiving and sending.

But we need to remember that it's not just the client's call to
``send_all`` that might block: the server's call to ``send_all`` can
also get into a situation where it blocks until the client calls
``receive_some``. So if the server is waiting for ``send_all`` to
finish before it calls ``receive_some``, and our client also waits for
``send_all`` to finish before it calls ``receive_some``,... we have a
problem! The client won't call ``receive_some`` until the server has
called ``receive_some``, and the server won't call ``receive_some``
until the client has called ``receive_some``. If our client is written
to alternate between sending and receiving, and the chunk of data it's
trying to send is large enough (e.g. 10 megabytes will probably do it
in most configurations), then the two processes will `deadlock
<https://en.wikipedia.org/wiki/Deadlock>`__.

Moral: Trio gives you powerful tools to manage sequential and
concurrent execution. In this example we saw that the server needs
``send`` and ``receive_some`` to alternate in sequence, while the
client needs them to run concurrently, and both were straightforward
to implement. But when you're implementing network code like this then
it's important to think carefully about flow control and buffering,
because it's up to you to choose the right execution mode!

Other popular async libraries like `Twisted
<https://twistedmatrix.com/>`__ and :mod:`asyncio` tend to paper over
these kinds of issues by throwing in unbounded buffers everywhere.
This can avoid deadlocks, but can introduce its own problems and in
particular can make it difficult to keep `memory usage and latency
under control
<https://vorpus.org/blog/some-thoughts-on-asynchronous-api-design-in-a-post-asyncawait-world/#three-bugs>`__.
While both approaches have their advantages, Trio takes the position
that it's better to expose the underlying problem as directly as
possible and provide good tools to confront it head-on.

.. note::

   If you want to try and make the deadlock happen on purpose to see
   for yourself, and you're using Windows, then you might need to
   split the ``send_all`` call up into two calls that each send half of
   the data. This is because Windows has a `somewhat unusual way of
   handling buffering
   <https://stackoverflow.com/questions/28785626/what-is-the-size-of-a-socket-send-buffer-in-windows>`__.


When things go wrong: timeouts, cancellation and exceptions in concurrent tasks
-------------------------------------------------------------------------------

TODO: give an example using :func:`fail_after`

TODO: explain :exc:`Cancelled`

TODO: explain how cancellation is also used when one child raises an
exception

TODO: show an example :exc:`MultiError` traceback and walk through its
structure

TODO: maybe a brief discussion of :exc:`KeyboardInterrupt` handling?

..
   Timeouts
   --------

   XX todo

   timeout example::

      async def counter():
          for i in range(100000):
              print(i)
              await trio.sleep(1)

      async def main():
          with trio.fail_after(10):
              await counter()

   you can stick anything inside a timeout block, even child tasks

     [show something like the first example but with a timeout – they
     both get cancelled, the cancelleds get packed into a multierror, and
     then the timeout block catches the cancelled]

   brief discussion of KI?
   tasks-with-trace.py + control-C is pretty interesting
   or maybe leave it for a blog post?
