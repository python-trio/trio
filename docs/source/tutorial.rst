Trio tutorial
=============

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
like Trio, so we leave it out. We'll include some links at the end in
case you're the kind of person who's curious to know how it works
under the hood, but you should still read this section first, because
the internal details will make much more sense once you understand
what it's all for.


Installing Trio
---------------

1. Make sure you're using Python 3.5 or newer.

2. ``pip install trio``

3. You're good to go!


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
but it's pointless: not only could it be just as easily written as a
regular function, but that would actually make it more useful, because
then you could call it from anywhere. ``double_sleep`` is a much more
typical example. Practical async applications are written like a
sandwich: :func:`trio.run` calls one of your async functions, which
calls another of your async functions, ..., which eventually calls
trio primitives like :func:`trio.sleep`. It's exactly those functions
which come in between :func:`trio.run` and :func:`trio.sleep` that
need to be async, making up our async sandwich's tasty async
filling. Other functions (e.g., helpers you call along the way) should
generally be regular, non-async functions.


Warning: don't forget to ``await``
----------------------------------

Now would be a good time to open up a Python prompt and experiment a
little with writing simple async functions and running them with
``trio.run``.

At some point in this process, you'll probably write some code like
this, that's missing an ``await``::

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

You might think that when this happens, Python would raise an
error. But unfortunately, what you actually get is:

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

Here's what's going on. In Trio, every time we use ``await`` it's to
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
``await``, and see what you get. Or try this::

   trio.run(double_sleep(3))

This way you'll be prepared for when it happens to you for real.

And remember: ``RuntimeWarning: coroutine '...' was never awaited``
means you need to find and fix your missing ``await``.


Okay, let's do something cool
-----------------------------

So now we've started using trio, but so far all we've learned to do is
write functions that print things and sleep for various lengths of
time. Interesting enough, but we could just as easily have done that
with :func:`time.sleep`. ``async/await`` is useless!

Well, not really. Trio has one more trick up its sleeve, that makes
async functions more powerful than regular functions: it can run
multiple async function *at the same time*. Here's an example::

   import trio

   async def child1():
       print("  child1: started! sleeping now...")
       await trio.sleep(1)
       print("  child1: exiting!")

   async def child2():
       print("  child2 started! sleeping now...")
       await trio.sleep(1)
       print("  child2 exiting!")

   async def parent():
       print("parent: started!")
       async with trio.open_nursery() as nursery:
           print("parent: spawning child1...")
           nursery.spawn(child1)

           print("parent: spawning child2...")
           nursery.spawn(child2)

           print("parent: waiting for children to finish...")
           # -- we exit the nursery block here --
       print("parent: all done!")

   trio.run(parent)

There's a lot going on in here, so we'll take it one step at a
time. First, we define two async functions ``child1`` and
``child2``. This part should be familiar from the last section.

Next, we define ``parent`` as an async function that's going to run
``child1`` and ``child2`` concurrently. It does this by creating a
"nursery", and then "spawning" them both in the nursery (we'll go over
this in more detail below). The output looks like:

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

Notice that the output from ``child1`` and ``child2`` is mixed
together, and that the whole program only takes 1 second to run, even
though we have two calls to ``trio.sleep(1)``.

Now, if you're familiar with programming using threads, this might
look familiar – and that's intentional. But it's important to realize
that *there are no threads here*. All of this is happening in a single
thread.

:class:`trio.Task`
(define terminology: "task")

Under the covers, trio.run and trio.sleep work together to make this
happen: trio.sleep has access to some special magic that lets it pause
its entire callstack and send a message to trio.run requesting that it
be woken up again after N seconds. (Inside the Python interpreter,
it's this special magic that ``async/await`` are all about.) Then when
trio.run gets this message, it makes a note about when ``child1``
wants to be woken up, and switches to executing ``child2``, until
``child2`` calls ``trio.sleep``...

(this is also why our async sandwich is important: the two pieces of
bread talk to each other! curio.run + trio.sleep or trio.run +
curio.sleep is not going to work out.)

So whenever we do something that will block a task for a while – like
waiting for time to pass with ``trio.sleep``, or waiting for data to
arrive over the network – then we use ``await``. (Hence the name:
``await`` is for waiting.) From the point of view of ``child1``, this
is simple straight-line code: it prints a message, blocks for 1 second
in sleep, and then prints another message. But while ``child1`` is
blocked, the overall can keep getting useful work done.

quick quiz: Try replacing the ``await trio.sleep(1)`` calls with
``time.sleep(1)`` in our original script. What happens if you run it
now? Why?

if you've used threads before, this is very similar to starting

.. code-block:: python

   import threading
   import time

   def child1():
       print("child1 started!")
       time.sleep(1)
       print("child1 exiting!")

   def child2():
       print("child2 started!")
       time.sleep(1)
       print("child2 exiting!")

   def main():
       print("main started!")
       thread1 = threading.Thread(target=child1)
       thread1.start()
       thread2 = threading.Thread(target=child2)
       thread2.start()
       thread1.join()
       thread2.join()
       print("main exiting!")

   main()

threads versus tasks:
either way, only one function is running at a time, because of the GIL

Async programming takes a kind of "if you can't beat 'em, join 'em"
approach to the GIL: if we're going to have a GIL anyway, let's take
advantage of that to make our API easier to use!

downsides:

- extra ceremony with ``async`` and ``await``

- explicit yielding means it's possible for one task to accidentally
  block the app

upsides:

- control over interleaving https://glyph.twistedmatrix.com/2014/02/unyielding.html

- much more scalable – thousands of concurrent tasks is no big deal,
  versus https://twitter.com/hynek/status/771790449057132544

- because these "threads" are implemented in Python, we can have rich
  semantics – nurseries, cancellation, introspection, etc.

generally much easier to reason about

answer: [show transcript] [in trio you *NEVER SWITCH* except when
using ``await``. If there's a stretch of code that doesn't have any
awaits in it, then that code will run straight through, and all the
other tasks will have to wait for it to finish! For example, in the
threaded version, it's possible to see something like

  parent: started child1
  child1: running!
  parent: started child2

but in the trio version this is *not* possible, because there's no
``await`` there. The only ``await`` in ``parent`` is the invisible one
at the exit from the ``async with`` block.

This is both good and bad: it makes it much easier to reason about
things, because there's less opportunity for different tasks to
interfere with each other. For example, an expression like ``x += 1``
might be unsafe in a threaded program, but is always safe in Trio.
But OTOH it means that if you aren't careful, then one task can end up
hogging control and stopping other tasks from executing. Which is bad
if, say, you have 1000 tasks answering different HTTP requests – 999
of your users will be left staring at a blank screen and waiting for
their data! Fortunately though there are some ways that trio can help
you avoid this, which we'll talk about later.]

also introduces ``async with``. In addition to async functions,
there's a whole parallel world of async constructions. You can have
async methods (like a regular method, but defined with ``async def``
and called like ``await obj.doit()``), async context managers (like a
regular context manager, but the enter and exit functions are async,
and instead of ``with`` you use ``async with``), async iterators
(with regular iterators you fetch the next value by calling the
regular method ``__next__``, or use a ``for`` loop; with async iterators you
fetch the next value by calling the async method ``__anext__``, or use
an ``async for`` loop),

async generators

[also say explicitly that you can only use ``async with``, ``async
for``, inside an ``async def``]

(maybe a table?)

these cases all work the same though: if you have a context manager
that wants to call an async function, then it has to be an async
context manager, etc. Here ``open_nursery()`` is an async context
manager, because it blocks waiting for all the child tasks to finish.



https://snarky.ca/how-the-heck-does-async-await-work-in-python-3-5/
