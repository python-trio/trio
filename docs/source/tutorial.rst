 Trio tutorial
===============

Welcome to the Trio tutorial! Here we'll try to give a gentle
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
the implementation will make more sense once you understand what it's
all for.


Async functions
---------------

Python 3.5 added a major new feature: async functions. Using Trio is
all about writing async functions, so lets start there.

An async function is defined like a normal function, except you write
``async def`` instead of ``def``::

   def regular_double(x):
       return 2 * x

   async def async_double(x):
       return 2 * x

(We'll sometimes refer to regular functions like ``regular_double`` as
"synchronous functions", to distinguish them from async functions.)

From a user's point of view, there are two differences between an
async function and a regular function:

1. To call an async function, you have to use the ``await``
   keyword. So instead of writing ``regular_double(3)``, we write
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

=======================  ===================================  ===================
If a function like this  wants to call a functions like this  is it gonna happen?
=======================  ===================================  ===================
async                    sync                                 yep
async                    async                                sure
sync                     sync                                 of course
sync                     async                                NOPE
=======================  ===================================  ===================

So in summary: The entire difference between an async function and a
regular function is that an async function has a super-power: it can
call other async functions.

This immediately raises two questions: how, and why? Specifically:

When your Python program starts up, it's running in regular old sync
mode. Once we have an async function we can call other async
functions, but *how* do we call that first async function?

And if the only reason to write an async function is that it can call
other async functions, *why* would on earth would we ever use them in
the first place? I mean, as superpowers go this seems a bit
pointless. Wouldn't it be simpler to just... not use any async
functions?

This is where an async library like Trio comes in. It provides two
things:

1. A runner function, which is a special *synchronous* function that
   takes and runs an *asynchronous* function. In Trio, this is
   ``trio.run``::

      import trio

      async def async_double(x):
          return 2 * x

      trio.run(async_double, 3)  # returns 6

   So that answers the "how" part.

2. A bunch of useful async functions – in particular, functions for
   doing I/O. So that answers the "why": these functions are async,
   and they're useful, so if you want to use them, you have to write
   async code. For example, there's ``trio.sleep``, which does the
   obvious thing:

   .. code-block:: python3

      import trio

      async def double_sleep(x):
          await trio.sleep(2 * x)

      trio.run(double_sleep, 3)  # does nothing for 6 seconds then returns

Our ``async_double`` function is actually a bad example. I mean, it
works, it's fine, but it's pointless: you could just as easily write
it as a regular function, and doing that makes it more useful, because
then you can call it from anywhere. Generally async applications are
like a sandwich: on one side you have ``trio.run``, on the other side
you have async functions like ``trio.sleep``, and your code makes the
tasty async filling in between.


Side note: the missing ``await``
--------------------------------

Now would be a good time to open up a Python prompt and experiment a
little with writing simple async functions and running them with
``trio.run``.

At some point in this process, you'll probably write some code like
this, with a missing ``await``::

   import trio

   async def broken_double_sleep(x):
       print("*yawn* Going to sleep")
       # Whoops, we forgot the 'await'!
       trio.sleep(2 * x)
       print("Woke up again, feeling well rested!")

   trio.run(broken_double_sleep, 3)

You might think that when this happens, Python would raise an
error. But unfortunately, what you actually get is that the code runs
instantly, and prints something like::

   >>> trio.run(broken_double_sleep, 3)
   *yawn* Going to sleep
   Woke up again, feeling well rested!
   __main__:4: RuntimeWarning: coroutine 'sleep' was never awaited
   >>>

Or if you're using PyPy, you might even get no warning at all, until a
GC collection runs::

   >>>> trio.run(broken_double_sleep, 3)
   *yawn* Going to sleep
   Woke up again, feeling well rested!
   >>>> # what the ... ??
   >>>> import gc
   >>>> gc.collect
   /home/njs/pypy-3.5-nightly/lib-python/3/importlib/_bootstrap.py:191: RuntimeWarning: coroutine 'sleep' was never awaited
   if _module_locks.get(name) is wr:    # XXX PyPy fix?
   0
   >>>>

This is an *incredibly common mistake*. You will mess this
up. Everyone does. And Python will not help you as much as you'd hope
😞. The key thing to remember is: if you see the magic words
``RuntimeWarning: coroutine '...' was never awaited``, then this
*always* means that you made the mistake of leaving out an ``await``
somewhere, and you should ignore all the other error messages you see
and go fix that first, because there's a good chance the other stuff
is just collateral damage.

What's going on here is: in Trio, every time we use ``await`` it's to
call an async function, and every time we call an async function we
use ``await``. But Python's trying to keep its options open for other
libraries that are *ahem* a little less organized about things. So
while for our purposes we can think of ``await trio.sleep(...)`` as a
single piece of syntax, Python thinks of it as two things: first a
function call that returns this weird "coroutine" object::

   >>> trio.sleep(3)
   <coroutine object sleep at 0x7f5ac77be6d0>

and then that thing gets passed to ``await``, which actually runs the
function. So if you forget ``await``, then two bad things happen: your
code doesn't actually run, and you get this coroutine object where you
might have been expecting something else, like a number::

   >>> async_double(3) + 1
   TypeError: unsupported operand type(s) for +: 'coroutine' and 'int'

("I thought you said you weren't going to mention coroutines!" Yes,
well, *I* didn't mention coroutines, Python did. Take it up with
Guido ;-).)

If you didn't already mess this up naturally, then give it a try on
purpose: try writing some code with a missing ``await``, or an extra
``await``, and see what you get. Or try this::

   trio.run(double_sleep(3))

This way you'll be prepared for when it happens to you later.


Okay, let's do some cool stuff
------------------------------


.. code-block:: python

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

       print("parent: all done!")

   trio.run(parent)

Output::



(note another common mistake: forgetting the call to ``trio.run``!)

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

quick quiz: Try replacing the ``await trio.sleep(1)`` calls with
``time.sleep(1)`` in our original script. What happens if you run it
now? Why?

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
