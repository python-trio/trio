
We assume that you're familiar with Python in general, but not at all
familiar with asynchronous programming or Python's new ``async/await``
feature.

Also, we assume that your goal is to *use* Trio to write interesting
programs, so we won't go into the nitty-gritty details of how
``async/await`` is implemented inside the Python interpreter. You only
really need to know about those if you want to *implement* a library
like trio. We'll include some links at the end for if you're curious
to know how it works under the hood – but you should read this section
first, because the implementation will make more sense once you
understand the end goal.


An async function is defined like a normal function, except you write
``async def`` instead of ``def``:

.. code-block:: python

   def regular_double(x):
       return 2 * x

   async def async_double(x):
       return 2 * x

(We'll sometimes refer to regular functions like ``regular_double`` as
"synchronous functions", to distinguish them from async functions.)

There are two differences between an async function and a regular
function:

1. To call an async function, you have to use the ``await``
   keyword. So instead of writing ``regular_double(3)``, we write
   ``await async_double(3)``.

2. A regular function can't use the ``await`` keyword. If you try it,
   you'll get a syntax error:

   .. code-block:: python

      def print_double(x):
          print(await async_double(x))   # <-- SyntaxError here

   But inside an async function, ``await`` is allowed:

   .. code-block:: python

      async def print_double(x):
          print(await async_double(x))   # <-- OK!

Together, these two facts mean that async functions can call both
regular functions and async functions, but regular functions can't
call async functions. So in a sense, async functions are more powerful
than regular functions... but in a somewhat weird way.

should have two questions:

- if the only reason to have an async function is that it lets you
  call other async functions, then why have them at all? it seems
  circular.

- if only an async function can call an async function, then how do I
  run one in the first place?

[put in a sidebar somewhere here about what happens if you try to call
an async function without await. You might think it would be an error,
but actually the ``await`` and function call are two separate
pieces. If you try you get this weird "coroutine object". Key
points: (1) in trio you *always* write it like ``await foo(...)``, so
you might as well pretend that this really is one piece of
syntax... but (2) unfortunately, if you mess it up, then python won't
raise a nice error. And when you're getting started, you will mess it
up. Repeatedly. Happens to everyone. And creates bizarre bugs, since
the function you think you called actually never gets executed. So (3)
learn to recognize this warning message: ... If you see this, it
always means that you forgot an ``await``, and you should fix that
before worrying about any other errors you're getting.]

why is it useful to be able to call an async function? well there are
lots of functions inside trio that async -- like trio.sleep
how do you call an async function then? you need a

trio.run(trio.sleep, 1)    # sleeps for 1 second
trio.run(async_double, 3)  # returns 6

.. code-block:: python

   import trio

   async def child1():
       print("child1 started!")
       await trio.sleep(1)
       print("child1 exiting!")

   async def child2():
       print("child2 started!")
       await trio.sleep(1)
       print("child2 exiting!")

   async def main():
       print("main started!")
       async with trio.open_nursery() as nursery:
           nursery.spawn(child1)
           nursery.spawn(child2)
       print("main exiting!")

   trio.run(main)

(define terminology: "task")

Under the covers, trio.run and trio.sleep work together to make this
happen: trio.sleep has access to some special magic that lets it pause
its entire callstack and send a message to trio.run requesting that it
be woken up again after N seconds. (Inside the Python interpreter,
it's this special magic that ``async/await`` are all about.) Then when
trio.run gets this message, it makes a note about when ``child1``
wants to be woken up, and switches to executing ``child2``, until
``child2`` calls ``trio.sleep``...

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
other tasks will have to wait for it to finish! This is both good and
bad: it makes it much easier to reason about things, because there's
less opportunity for different tasks to interfere with each other; but
OTOH it means that if you aren't careful, then one task can end up
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
