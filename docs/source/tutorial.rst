Tutorial
========

.. currentmodule:: trio

Welcome to the Trio tutorial! Trio is a modern Python library for
writing asynchronous applications – often, but not exclusively,
asynchronous network applications. Here we'll try to give a gentle
introduction to asynchronous programming with Trio.

We assume that you're familiar with Python in general, but don't worry
– we don't assume you know anything about asynchronous programming or
Python's new ``async/await`` feature.

Also, we assume that your goal is to *use* Trio to write interesting
programs, so we won't go into the nitty-gritty details of how
``async/await`` is implemented inside the Python interpreter. The word
"coroutine" is never mentioned. The fact is, you really don't *need*
to know any of that stuff unless you want to *implement* a library
like Trio, so we leave it out. We'll include some links in case you're
the kind of person who's curious to know how it works under the hood,
but you should still read this section first, because the internal
details will make much more sense once you understand what it's all
for.


Before you begin
----------------

1. Make sure you're using Python 3.5 or newer.

2. ``pip install trio``

3. Can you ``import trio``? If so then you're good to go!


Async functions
---------------

Python 3.5 added a major new feature: async functions. Using Trio is
all about writing async functions, so lets start there.

An async function is defined like a normal function, except you write
``async def`` instead of ``def``::

   # A regular function
   def regular_double(x):
       return 2 * x

   # An async function
   async def async_double(x):
       return 2 * x

(We'll sometimes refer to regular functions like ``regular_double`` as
"synchronous functions", to distinguish them from async functions.)

From a user's point of view, there are two differences between an
async function and a regular function:

1. To call an async function, you have to use the ``await``
   keyword. So instead of writing ``regular_double(3)``, you write
   ``await async_double(3)``.

2. A regular function can't use the ``await`` keyword. If you try it,
   you'll get a syntax error::

      def print_double(x):
          print(await async_double(x))   # <-- SyntaxError here

   But inside an async function, ``await`` is allowed::

      async def print_double(x):
          print(await async_double(x))   # <-- OK!

(Now you see why this new feature is called ``async/await`` for
short.)

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

So in summary: As a user, the entire difference between async
functions and regular functions is that async functions have a
superpower: they can call other async functions.

This immediately raises two questions: how, and why? Specifically:

When your Python program starts up, it's running regular old sync
code. So there's a chicken-and-the-egg problem: once we're running an
async function we can call other async functions, but *how* do we call
that first async function?

And, if the only reason to write an async function is that it can call
other async functions, *why* would on earth would we ever use them in
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
   in the matter! (Well, OK, you could just not use trio. That's a
   legitimate option. But it turns out that the ``async/await`` stuff
   is actually a good thing, for reasons we'll discuss a little bit
   later.)

   Here's an example function that uses ``trio.sleep``, which does the
   obvious thing:

   .. code-block:: python3

      import trio

      async def double_sleep(x):
          await trio.sleep(2 * x)

      trio.run(double_sleep, 3)  # does nothing for 6 seconds then returns

So it turns out our ``async_double`` function is actually a bad
example. I mean, it works, it's fine, there's nothing *wrong* with it,
but it's pointless: it could just as easily be written as a regular
function, and that would actually make it more
useful. ``double_sleep`` is a much more typical example: we have to
make it async, because it calls another async function. The end result
is a kind of async sandwich, with trio on both sides and our code in
the middle::

  trio.run -> double_sleep -> trio.sleep

This "sandwich" structure is typical for async code; in general, it
looks like::

  trio.run -> [async function] -> ... -> [async function] -> trio.whatever

It's exactly the functions on the path between :func:`trio.run` and
``trio.whatever`` that have to be async, making up our async
sandwich's tasty async filling. Other functions (e.g., helpers you
call along the way) should generally be regular, non-async functions.


Warning: don't forget to ``await``
----------------------------------

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
       start_time = time.time()
       # Whoops, we forgot the 'await'!
       trio.sleep(2 * x)
       sleep_time = time.time() - start_time
       print("Woke up after {:.2f} seconds, feeling well rested!".format(sleep_time))

   trio.run(broken_double_sleep, 3)

You might think that Python would raise an error here. But
unfortunately, it doesn't. What you actually get is:

.. code-block:: none

   >>> trio.run(broken_double_sleep, 3)
   *yawn* Going to sleep
   Woke up again after 0.00 seconds, feeling well rested!
   __main__:4: RuntimeWarning: coroutine 'sleep' was never awaited
   >>>

This is clearly broken – 0.00 seconds is not long enough to feel well
rested! The exact place where the warning is printed might vary,
because it depends on the whims of the garbage collector. If you're
using PyPy, you might not even get a warning at all until the next GC
collection runs:

.. code-block:: none

   # On PyPy:
   >>>> trio.run(broken_double_sleep, 3)
   *yawn* Going to sleep
   Woke up again after 0.00 seconds, feeling well rested!
   >>>> # what the ... ??
   >>>> import gc
   >>>> gc.collect()
   /home/njs/pypy-3.5-nightly/lib-python/3/importlib/_bootstrap.py:191: RuntimeWarning: coroutine 'sleep' was never awaited
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
good chance the other stuff is just collateral damage. (I'm not even
sure what all that other junk in the PyPy output is. Fortunately I
don't need to know, I just need to fix my function!)

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

("I thought you said you weren't going to mention coroutines!" Yes,
well, *I* didn't mention coroutines, Python did. Take it up with
Guido ;-).)

If you didn't already mess this up naturally, then give it a try on
purpose: try writing some code with a missing ``await``, or an extra
``await``, and see what you get. This way you'll be prepared for when
it happens to you for real.

And remember: ``RuntimeWarning: coroutine '...' was never awaited``
means you need to find and fix your missing ``await``.


Okay, let's see something cool already
--------------------------------------

So now we've started using trio, but so far all we've learned to do is
write functions that print things and sleep for various lengths of
time. Interesting enough, but we could just as easily have done that
with :func:`time.sleep`. ``async/await`` is useless!

Well, not really. Trio has one more trick up its sleeve, that makes
async functions more powerful than regular functions: it can run
multiple async function *at the same time*. Here's an example:

.. _tutorial-example-tasks-intro:

.. literalinclude:: tutorial/tasks-intro.py
   :linenos:

There's a lot going on in here, so we'll take it one step at a
time. In the first part, we define two async functions ``child1`` and
``child2``. This part should be familiar from the last section:

.. literalinclude:: tutorial/tasks-intro.py
   :linenos:
   :lineno-match:
   :start-at: async def child1
   :end-at: child2 exiting

Next, we define ``parent`` as an async function that's going to call
``child1`` and ``child2`` concurrently:

.. literalinclude:: tutorial/tasks-intro.py
   :linenos:
   :lineno-match:
   :start-at: async def parent
   :end-at: all done!

It does this by using a mysterious ``async with`` statement to create
a "nursery", and then "spawns" child1 and child2 into the nursery.

The ``async with`` part is actually pretty simple. In regular Python,
a statement like ``with someobj: ...`` instructs the interpreter to
call ``someobj.__enter__()`` at the beginning of the block, and to
call ``someobj.__exit__()`` at the end of the block (this is glossing
over some subtleties around exception handling, but that's the basic
idea). Here ``someobj`` is called a "context manager". An ``async
with`` does exactly the same thing, except that where a regular
``with`` statement calls regular methods, an ``async with`` statement
calls async methods: it basically does ``await someobj.__aenter__()``
and ``await someobj.__aexit__()``, and now we call ``someobj`` an
"async context manager". So in short: ``with`` blocks are a shorthand
for calling some functions, and now that we have two kinds of
functions we need two kinds of ``with`` blocks. If you understand
async functions, then you understand ``async with``.

.. note::

   This example doesn't use them, but while we're here we might as
   well mention the last piece of new syntax that async/await added:
   ``async for``. An ``async for`` loop is just like a ``for`` loop,
   except that where a ``for`` loop does ``iterator.__next__()`` to
   fetch the next item, an ``async for`` does ``await
   async_iterator.__anext__()``. Now you understand all of
   async/await. Basically just remember that it involves sandwiches
   and sticking the word "async" in front of everything, and you'll do
   fine.

So let's look at ``parent`` one last time:

.. literalinclude:: tutorial/tasks-intro.py
   :linenos:
   :lineno-match:
   :start-at: async def parent
   :end-at: all done!

There are only 4 lines of code that really do anything here. On line
17, we use :func:`trio.open_nursery` to get a "nursery" object, and
then inside the ``async with`` block we call ``nursery.spawn`` twice,
on lines 19 and 22. ``nursery.spawn(async_fn)`` is another way to call
an async function: it asks trio to start running this function, but
then returns immediately without waiting for the function to
finish. So after our two calls to ``nursery.spawn``, ``child1`` and
``child2`` are now running in the background. And then at line 25, the
commented line, we hit the end of the ``async with`` block, and the
nursery's ``__aexit__`` function runs. What this does is force
``parent`` to stop here and wait for all the children in the nursery
to exit. This is why you have to use ``async with`` to get a nursery:
it gives us a way to make sure that the child calls can't run away and
get lost. One reason this is important is that if there's a bug or
other problem in one of the children, and it raises an exception, then
it lets us propagate that exception into the parent; in many other
frameworks, exceptions like this are just discarded. Trio never
discards exceptions.

Anyway, phew, that was a lot of description. Let's try running it and
see what we get:

.. code-block:: none

   parent: started!
   parent: spawning child1...
   parent: spawning child2...
   parent: waiting for children to finish...
     child2 started! sleeping now...
     child1: started! sleeping now...
       [... 1 second passes ...]
     child1: exiting!
     child2 exiting!
   parent: all done!

(Your output might have order of the "started" and/or "exiting" lines
swapped compared to to mine.)

Notice that ``child1`` and ``child2`` both start together and then
both exit together, and that the whole program only takes 1 second to
run, even though we made two calls to ``trio.sleep(1)``, which should
take two seconds. So it looks like ``child1`` and ``child2`` really
are running at the same time!

Now, if you're familiar with programming using threads, this might
look familiar – and that's intentional. But it's important to realize
that *there are no threads here*. All of this is happening in a single
thread. To remind us of this, we use slightly different terminology:
instead of spawning two "threads", we say that we spawned two
"tasks". There are two differences between tasks and threads: (1) many
tasks can take turns running on a single thread, and (2) with threads,
the Python interpreter/operating system can switch which thread is running
whenever they feel like it; with tasks, we can only switch at
certain designated places we call :ref:`"yield points" <yield-points>`.


.. _tutorial-instrument-example:

Task switching illustrated
--------------------------

The big idea behind async/await-based libraries is this one of running
lots of tasks on a single thread by switching between them at the
appropriate places. If all you want to do is use these libraries, then
you don't need to understand all the nitty-gritty detail of how this
works – but it's very useful to at least have a general intuition. To
help build that intuition, let's look more closely at how trio
actually ran our example from the last section.

Fortunately, trio provides a :ref:`rich set of tools for inspecting
and debugging your programs <instrumentation>`. Here we want to watch
:func:`trio.run` at work, which we can do by implementing an
:class:`~trio.abc.Instrument` class to log various events as they
happen:

.. literalinclude:: tutorial/tasks-with-trace.py
   :pyobject: Tracer

Then we re-run our example program from the previous section, but this
time we pass :func:`trio.run` a ``Tracer`` object:

.. literalinclude:: tutorial/tasks-with-trace.py
   :start-at: trio.run

This generates a *lot* of output, so we'll go through it one step at a
time.

First, there's a bit of chatter while trio sets up some internal
housekeeping. In the middle there though you can see that trio has
created a task for the ``__main__.parent`` function, and "scheduled"
it (i.e., made a note that it's ready to run):

.. code-block:: none

   $ python3 tutorial/tasks-with-trace.py
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

Once the initial housekeeping is done, it then starts our ``parent``
function, and you can see it printing and creating the two child
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
does this happen? It involves some cooperation between
:func:`trio.run` and :func:`trio.sleep`: :func:`trio.sleep` has access
to some special magic that lets it pause its entire callstack, so it
sends a note to :func:`trio.run` requesting to be woken again after 1
second, and then suspends the task. And when the task is suspended,
Python gives control back to :func:`trio.run`, which decides what to
do next. (If this sounds similar to the way that generators can
suspend execution by doing a ``yield``, then that's not a coincidence:
inside the Python interpreter, generators and async functions share a
lot of their implementations.)

.. note::

   You might wonder whether you can mix-and-match primitives from
   different async libraries. For example, could we use
   :func:`trio.run` together with :func:`asyncio.sleep`? We can't, and
   the paragraph above is why: the two sides of our async sandwich
   have a private language they use to talk to each
   other, and different libraries use different languages. So if you
   try to call :func:`asyncio.sleep` from inside a :func:`trio.run`,
   then trio will get very confused indeed and probably blow up in
   some dramatic way.

Only async functions have access to the special magic for suspending a
task, so only async functions can cause the program to switch to a
different task. What this means if a call *doesn't* have an ``await``
on it, then you know that it *can't* be a place where your task will
be suspended. This makes tasks much `easier to reason about
<https://glyph.twistedmatrix.com/2014/02/unyielding.html>`__ than
threads, because there are far fewer ways that tasks can be
interleaved with each other and stomp on each others' state. Trio also
makes some :ref:`further guarantees beyond that <yield-points>`, but
that's the big one.

And now you also know why ``parent`` had to use an ``async with`` to
open the nursery: if we had used a regular ``with`` block, then it
wouldn't have been able to pause at the end and wait for the children
to finish; we need our cleanup function to be async, which is exactly
what ``async with`` gives us.

Now, back to our execution trace. To recap: at this point ``parent``
is waiting on ``child1`` and ``child2``, and both children are
sleeping. So trio knows that there's nothing to be done until those
sleeps finish – unless possibly some external I/O event comes in. Of
course we aren't doing any I/O here so that won't happen, but in other
situations it could. So next it calls an operating system primitive to
put the whole process to sleep:

.. code-block:: none

   ### waiting for I/O for up to 0.9999009938910604 seconds

And in fact no I/O does arrive, so one second later we wake up again,
and trio looks around to see if there's anything to do. When it does,
it discovers the note that :func:`trio.sleep` sent, saying that this
is when the children should be woken up again:

.. code-block:: none

   ### finished I/O check (took 1.0006483688484877 seconds)
   ### task scheduled: __main__.child1
   ### task scheduled: __main__.child2

And then the children get to run, and this time they exit. Remember
how ``parent`` is waiting for that to happen? When they exit
``parent`` gets woken up:

.. code-block:: none

   >>> about to run one step of task: __main__.child2
     child2 exiting!
   ### task scheduled: __main__.parent
   ### task exited: __main__.child2
   <<< task step finished: __main__.child2

   >>> about to run one step of task: __main__.child1
     child1: exiting!
   ### task exited: __main__.child1
   <<< task step finished: __main__.child1

So after another check for I/O, ``parent`` wakes up. The nursery
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

And then, after a bit more internal bookkeeping, we're done:

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

You made it!

That was a lot of text, but again, you don't need to understand
everything here to use trio – in fact, trio goes to great lengths to
make tasks feel like they execute in a simple linear way. (Just like
your operating system goes to great lengths to make it feel like
single-threaded code executes in a simple linear way, even though
under the covers it's doing essentially the same things trio is.) But
it is useful to have a rough model in your head of how the code you
write is actually executed, and – most importantly – the consequences
of that for parallelism.

Alternatively, if this has just whetted your appetite and you want to
know more about how ``async/await`` works internally, then `this blog
post
<https://snarky.ca/how-the-heck-does-async-await-work-in-python-3-5/>`__
is a good explanation.


Best GIL ever
-------------

From trio's point of view, the problem with the GIL isn't that it
restricts parallelism. Of course it would be nice if Python had better
options for taking advantage of multiple cores, but that's an
extremely difficult problem to solve, and in the mean time there are
lots of problems where a single core is totally adequate – or if it
isn't, then process- or machine-level parallelism works fine.

No, the problem with the GIL is that it's a *lousy deal*: we give up
on using multiple cores, and in exchange we get... almost all the
challenges and mind bending bugs that come with real parallel
programming, and – to add insult to injury – `pretty poor scalability
<https://twitter.com/hynek/status/771790449057132544>`__. Threads in
Python just aren't that appealing.

Trio doesn't make your code run on multiple cores; in fact, as we saw
above, it's baked into trio's design that you never have two tasks
running at the same time. We're not so much overcoming the GIL as
embracing it. But if we're willing to accept that, plus a bit of extra
bookkeeping to keep track of these new ``async`` and ``await``
keywords, then in exchange we get:

* Excellent scalability: running 10,000+ tasks simultaneously is not a
  big deal, so long as their total CPU demands don't exceed what a
  single core can provide.

* Fancy features: most threading systems are implemented in C and
  restricted to whatever features the operating system provides. In
  trio our logic is all in Python, which makes it possible to
  implement powerful and ergonomic features like :ref:`trio's
  cancellation system <cancellation>`.

* Code that's easier to reason about: the ``await`` keyword means that
  potential task-switching points are explicitly marked within each
  function. This `dramatically reduces
  <https://glyph.twistedmatrix.com/2014/02/unyielding.html>`__ the
  complexities of reasoning about concurrent programs.

Certainly it's not appropriate for every app... but there are a lot of
situations where the trade-offs here look pretty appealing.

There is one downside that's important to keep in mind, though. Making
yield points explicit gives you more control over how your tasks can
be interleaved – but with great power comes great responsibility. With
threads, the runtime environment is responsible for making sure that
each thread gets its fair share of running time. With trio, if some
task runs off and  without executing a yield
point, then... all your other tasks will just have to wait.

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



One of the major reasons why trio has such a rich
:ref:`instrumentation API <tutorial-instrument-example>` is to make it
possible to catch issues like this.


An echo server: low-level API
-----------------------------

XX maybe start with echo client so the structure is like our 2 child
one but with sockets instad of sleep

and then echo server to introduce the spawn-into-another-nursery
trick?

.. literalinclude:: tutorial/echo-server-low-level.py


An echo server: higher-level API
--------------------------------


Errors in concurrent tasks
--------------------------

walk through a multierror traceback


Timeouts
--------

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
