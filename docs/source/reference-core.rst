Trio's core functionality
=========================

.. module:: trio


Entering trio
-------------

If you want to use trio, then the first thing you have to do is call
:func:`trio.run`:

.. autofunction:: run


Time and clocks
---------------

Every call to :func:`run` has an associated clock.

By default, trio uses an unspecified monotonic clock, but this can be
changed by passing a custom clock object to :func:`run` (e.g. for
testing).

You should not assume that trio's internal clock matches any other
clock you have access to, including the clocks of other concurrent
calls to :func:`trio.run`!

The default clock is currently implemented as :func:`time.monotonic`
plus a large random offset. The idea here is to catch code that
accidentally uses :func:`time.monotonic` early, which should help keep
our options open for `changing the clock implementation later
<https://github.com/njsmith/trio/issues/33>`__, and (more importantly)
make sure you can be confident that custom clocks like
:class:`trio.testing.MockClock` will work with third-party libraries
you don't control.

.. autofunction:: current_time

.. autofunction:: sleep
.. autofunction:: sleep_until
.. autofunction:: sleep_forever

If you're a mad scientist or otherwise feel the need to take direct
control over the PASSAGE OF TIME ITSELF, then you can implement a
custom :class:`~trio.abc.Clock` class:

.. autoclass:: trio.abc.Clock
   :members:


Cancellation and timeouts
-------------------------

Trio has a rich, composable system for cancelling work, either
explicitly or when a timeout expires.


A simple timeout example
~~~~~~~~~~~~~~~~~~~~~~~~

In the simplest case, you can apply a timeout to a block of code::

   with move_on_after(30):
       result = await do_http_get("https://...")
       print("result is", result)
   print("with block finished")

We refer :func:`move_on_after` as creating a "cancel scope", that
contains all the code that runs inside the ``with`` block.

If the HTTP request finishes in less than 30 seconds, then ``result``
is set and the ``with`` block exits normally. If it does *not* finish
within 30 seconds, then the cancel scope becomes "cancelled", and any
attempt to call a blocking trio operation will raise a
:exc:`Cancelled` exception. This exception eventually propagates out
of ``do_http_get``, and is caught by the ``with`` block, and execution
continues on the line ``print("with block statement")``.

.. note::

   Note that this is a simple 30 second timeout for the entire body of
   the ``with`` statement. This is different from what you might have
   seen with other Python libraries, where timeouts often refer to
   something `more complicated
   <http://docs.python-requests.org/en/master/user/quickstart/#timeouts>`__. We
   think this way is easier to reason about.


Handling cancellation
~~~~~~~~~~~~~~~~~~~~~

Pretty much any code you write using trio needs to have some strategy
to handle :exc:`Cancelled` exceptions – even if you didn't set a
timeout, then your caller might (and probably will).

You can catch :exc:`Cancelled`, but you shouldn't! Or more precisely,
if you do catch it, then you should do some cleanup and then re-raise
it or otherwise let it continue propagating (unless you encounter an
error, in which case it's OK to let that propagate instead). To help
remind you of this fact, :exc:`Cancelled` inherits from
:exc:`BaseException`, like :exc:`KeyboardInterrupt` and
:exc:`SystemExit` do, so that it won't be caught by catch-all ``except
Exception:`` blocks.

It's also important in any long-running code to make sure that you
regularly check for cancellation, because otherwise timeouts won't
work! This happens implicitly every time you call a cancellable
operation; see :ref:`below <cancellable-primitives>` for details. If
you have a task that has to do a lot of work without any IO, then you
can use ``await sleep(0)`` to insert an explicit cancel+schedule
point.

Here's a rule of thumb for designing good trio-style ("trionic"?)
APIs: if you're writing a reusable function, then you shouldn't take a
``timeout=`` parameter, and instead let your caller worry about
it. This has several advantages. First, it leaves the caller's options
open for deciding how they prefer to handle timeouts – for example,
they might find it easier to work with absolute deadlines instead of
relative timeouts. If they're the ones calling into the cancellation
machinery, then they get to pick, and you don't have to worry about
it. Second, and more importantly, this makes it easier for others to
re-use your code. If you write a ``http_get`` function, and then I
come along later and write a ``log_in_to_twitter`` function that needs
to internally make several ``http_get`` calls, I don't want to have to
figure out how to configure the individual timeouts on each of those
calls – and with trio's timeout system, it's totally unnecessary.

Of course, this rule doesn't apply to APIs that need to impose
internal timeouts. For example, if you write a ``start_http_server``
function, then you probably should give your caller some way to
configure timeouts on individual requests.


Cancellation semantics
~~~~~~~~~~~~~~~~~~~~~~

You can freely nest cancellation blocks, and each :exc:`Cancelled`
exception "knows" which block it belongs to. So long as you don't stop
it, the exception will keep propagating until it reaches the block
that raised it, at which point it will stop automatically.

Here's an example::

   print("starting...")
   with move_on_after(5):
       with move_on_after(10):
           await sleep(20)
           print("sleep finished without error")
       print("move_on_after(10) finished without error")
   print("move_on_after(5) finished without error")

In this code, the outer scope will expire after 5 seconds, causing the
:func:`sleep` call to return early with a :exc:`Cancelled`
exception. Then this exception will propagate through the ``with
move_on_after(10)`` line until it's caught by the ``with
move_on_after(5)`` context manager. So this code will print:

.. code-block:: none

   starting...
   move_on_after(5) finished without error

The end result is that we have successfully cancelled exactly the work
that was happening within the scope that was cancelled.

Looking at this, you might wonder how we can tell whether the inner
block timed out – perhaps we want to do something different, like try
a fallback procedure or report a failure to our caller. To make this
easier, :func:`move_on_after`'s ``__enter__`` function returns an
object representing this cancel scope, which we can use to check
whether this scope caught a :exc:`Cancelled` exception::

   with move_on_after(5) as cancel_scope:
       await sleep(10)
   print(cancel_scope.cancelled_caught)  # prints "True"

The ``cancel_scope`` object also allows you to check or adjust tvhis
scope's deadline, explicitly trigger a cancellation without waiting
for the deadline, check if the scope has already been cancelled, and
so forth – see :func:`open_cancel_scope` below for the full details.

.. _blocking-cleanup-example:

Cancellations in trio are "level triggered", meaning that once a block
has been cancelled, *all* cancellable operations in that block will
keep raising :exc:`Cancelled`. This helps avoid some pitfalls around
resource clean-up. For example, imagine that we have a function that
connects to a remote server and sends some messages, and then cleans
up on the way out::

   with move_on_after(TIMEOUT):
       conn = make_connection()
       try:
           await conn.send_hello_msg()
       finally:
           await conn.send_goodbye_msg()

Now suppose that the remote server stops responding, so our call to
``await conn.send_hello_msg()`` hangs forever. Fortunately, we were
clever enough to put a timeout around this code, so eventually the
timeout will expire and ``send_hello_msg`` will raise
:exc:`Cancelled`. But then, in the ``finally`` block, we make another
blocking operation, which will also hang forever! At this point, if we
were using :mod:`asyncio` or another library with "edge-triggered"
cancellation, we'd be in trouble: since our timeout already fired, it
wouldn't fire again, and at this point our application would lock
up. But in trio, this *doesn't* happen: the ``await
conn.send_goodbye_msg()`` call is still inside the cancelled block, so
it will also raise :exc:`Cancelled`.

Of course, if you really want to make another blocking call in your
cleanup handler, trio will let you; it's trying to prevent you from
accidentally shooting yourself in the foot. Intentional foot-shooting
is no problem (or at least – it's not trio's problem). To do this,
create a new scope, and set its :attr:`shield` attribute to
:data:`True`::

   with move_on_after(TIMEOUT):
       conn = make_connection()
       try:
           await conn.send_hello_msg()
       finally:
           with move_on_after(CLEANUP_TIMEOUT) as cleanup_scope:
               cleanup_scope.shield = True
               await conn.send_goodbye_msg()

So long as you're inside a scope with ``shield = True`` set, then
you'll be protected from outside cancellations. Note though that this
*only* applies to *outside* cancellations: if ``CLEANUP_TIMEOUT``
expires then ``await conn.send_goodbye_msg()`` will still be
cancelled, and if ``await conn.send_goodbye_msg()`` call uses any
timeouts internally, then those will continue to work normally as
well. This is a pretty advanced feature that most people probably
won't use, but it's there for the rare cases where you need it.


.. _cancellable-primitives:

Cancellation and primitive operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

We've talked a lot about what happens when an operation is cancelled,
and how you need to be prepared for this whenever calling a
cancellable operation... but we haven't said which operations are
cancellable.

As far as trio's primitives go, the rule is: if it's in the trio
namespace, and you use ``await`` to call it, then it's
cancellable. Cancellable means:

* If you try to call it when inside a cancelled scope, then it will
  raise :exc:`Cancelled`.

* If it blocks, and while it's blocked then one of the scopes around
  it becomes cancelled, it will return early and raise
  :exc:`Cancelled`.

* Raising :exc:`Cancelled` means that the operation *did not
  happen*. If :meth:`~trio.socket.SocketType.send` raises
  :exc:`Cancelled`, then no bytes were sent. If
  :meth:`~trio.socket.SocketType.recv` raises :exc:`Cancelled` then no
  data was lost – it's still sitting in the socket recieve buffer
  waiting for you to call :meth:`~trio.socket.SocketType.recv`
  again. And so forth.

There are a few idiosyncratic cases where external constraints make it
impossible to fully implement these semantics. These are always
documented. There is also one systematic exception:

* Async cleanup operations – like ``__aexit__`` methods or async close
  methods – are cancellable just like anything else *except* that if
  they are cancelled, they still perform a minimum level of cleanup
  before raising :exc:`Cancelled`.

For example, closing a TLS-wrapped socket normally involves sending a
notification to the remote peer, so that they can be cryptographically
assured that you really meant to close the socket, and your connection
wasn't just broken by a man-in-the-middle attacker. But handling this
robustly is a bit tricky. Remember our :ref:`example
<blocking-cleanup-example>` above where the blocking
``send_goodbye_msg`` caused problems? That's exactly how closing a TLS
socket works: if the remote peer has disappeared, then we may never be
able to actually send our shutdown notification, and it would be nice
if we didn't block forever trying. Therefore, the ``close`` method on
a TLS-wrapped socket will *try* to send that notification – but if it
gets cancelled, then it will go ahead and close the underlying socket
before raising :exc:`Cancelled`, so at least you don't leak that
resource.


The cancellation API
~~~~~~~~~~~~~~~~~~~~

The primitive operation for creating a new cancellation scope is:

.. autofunction:: open_cancel_scope
   :with: cancel_scope

   Cancel scope objects provide the following interface:

   .. currentmodule:: None

   .. attribute:: deadline

      Read-write, :class:`float`. An absolute time on the current
      run's clock at which this scope will automatically become
      cancelled. You can adjust the deadline by modifying this
      attribute, e.g.::

         # I need a little more time!
         cancel_scope.deadline += 30

      Note that the core run loop alternates between running tasks and
      processing deadlines, so if the very first yield point after the
      deadline expires doesn't actually block, then it may complete
      before we process deadlines::

         with open_cancel_scope(deadline=current_time()):
             # current_time() is now >= deadline, so cancel should fire,
             # at the next yield point. BUT, if the next yield point
             # completes instantly -- e.g., a recv on a socket that
             # already has data pending -- then the operation may
             # complete before we process deadlines, and then it's too
             # late to cancel (the data's already been read from the
             # socket):
             await sock.recv(1)

             # But the next call after that *is* guaranteed to raise
             # Cancelled:
             await sock.recv(1)

      Defaults to :data:`math.inf`, which means "no deadline", though
      this can be overridden by the ``deadline=`` argument to
      :func:`~trio.open_cancel_scope`.

   .. attribute:: shield

      Read-write, :class:`bool`, default :data:`False`. So long as
      this is set to :data:`True`, then the code inside this scope
      will not receive :exc:`~trio.Cancelled` exceptions from scopes
      that are outside this scope. They can still receive
      :exc:`~trio.Cancelled` exceptions from (1) this scope, or (2)
      scopes inside this scope. You can modify this attribute::

         with open_cancel_scope() as cancel_scope:
             cancel_scope.shield = True
             # This cannot be interrupted by any means short of
             # killing the process:
             await sleep(10)

             cancel_scope.shield = False
             # Now this can be cancelled normally:
             await sleep(10)

      Defaults to :data:`False`, though this can be overridden by the
      ``shield=`` argument to :func:`~trio.open_cancel_scope`.

   .. method:: cancel()

      Cancels this scope immediately.

      This method is idempotent, i.e. if the scope was already
      cancelled then this method silently does nothing.

   .. attribute:: cancel_called

      Readonly :class:`bool`. Records whether this scope has been
      cancelled, either by an explicit call to :meth:`cancel` or by
      the deadline expiring.

   .. attribute:: cancelled_caught

      Readonly :class:`bool`. Records whether this scope caught a
      :exc:`~trio.Cancelled` exception. This requires two things: (1)
      the ``with`` block exited with a :exc:`~trio.Cancelled`
      exception, and (2) this scope is the one that was responsible
      for triggering this :exc:`~trio.Cancelled` exception.

   .. currentmodule:: trio

We also provide several convenience functions for the common situation
of just wanting to impose a timeout on some code:

.. autofunction:: move_on_after
   :with: cancel_scope

.. autofunction:: move_on_at
   :with: cancel_scope

.. autofunction:: fail_after
   :with: cancel_scope

.. autofunction:: fail_at
   :with: cancel_scope

Cheat sheet:

* If you want to impose a timeout on a function, but you don't care
  whether it timed out or not::

     with move_on_after(TIMEOUT):
         await do_whatever()
     # carry on!

* If you want to impose a timeout on a function, and then do some
  recovery if it timed out::

     with move_on_after(TIMEOUT) as cancel_scope:
         await do_whatever()
     if cancel_scope.cancelled_caught:
         # The operation timed out, try something else
         try_to_recover()

* If you want to impose a timeout on a function, and then if it times
  out then just give up and raise an error for your caller to deal
  with::

     with fail_after(TIMEOUT):
         await do_whatever()

It's also possible to check what the current effective deadline is,
which is sometimes useful:

.. autofunction:: current_effective_deadline


Tasks let you do multiple things at once
----------------------------------------

One of trio's core design principles is: *no implicit
concurrency*. Every function executes in a straightforward,
top-to-bottom manner, finishing each operation before moving on to the
next – *like Guido intended*.

But, of course, the entire point of an async library is to let you do
multiple things at once. The one and only way to do that in trio is
through the task spawning interface. So if you want your program to
walk *and* chew gum, this is the section for you.



.. autofunction:: open_nursery
   :async-with: nursery

   Nursery objects provide the following interface:

   .. currentmodule:: None

   .. method:: spawn(async_fn, *args, name=None)

      This is *the* method for creating

   .. attribute:: cancel_scope

      Creating a nursery also implicitly creates a cancellation
      scope. This is necessary so that the nursery can cancel all the
      child tasks if an error occurs.

   The remaining attributes and methods are mainly used for
   implementing new types of task supervisor:

   .. attribute:: monitor

      A :class:`~trio.UnboundedQueue` which receives each child
      :class:`~trio.Task` object when it exits.

   .. attribute:: children

      A :class:`frozenset` containing all the child
      :class:`~trio.Task` objects which are still running.

   .. attribute:: zombies

      A :class:`frozenset` containing all the child
      :class:`~trio.Task` objects which have exited, but not yet been
      reaped.

   .. method:: reap(task)

      Removes the given task from the :attr:`zombies` set.

      :raises ValueError: If the given *task* is not in :attr:`zombies`.

   .. method:: reap_and_unwrap(task)

      A convenience shorthand for::

         nursery.reap(task)
         return task.result.unwrap()

   .. currentmodule:: trio

.. class:: Task()

   .. attribute:: result

      If this :class:`Task` is still running, then its :attr:`result`
      attribute is ``None``. (This can be used to check whether a task
      has finished running.)

      Otherwise, this is a :class:`Result` object holding the value
      returned or the exception raised by the async function that was
      spawned to create this task.

   The next three methods allow another task to monitor the result of
   this task, even if it isn't supervising it:

   .. automethod:: wait

   .. automethod:: add_monitor

   .. automethod:: discard_monitor

   The remaining members are mostly useful for introspection and
   debugging:

   .. attribute:: name

      String containing this :class:`Task`\'s name. Usually (but not
      always) the name of the function this :class:`Task` is running.

   .. attribute:: coro

      This task's coroutine object. Example usage: extracting a stack
      trace.

   .. attribute:: parent_task

      This task's parent. Example usage: drawing a visualization of
      the task tree.

.. autofunction:: current_task()

.. autoclass:: Result

.. autoclass:: Value

.. autoclass:: Error

.. autoexception:: MultiError
   :members:

.. autofunction:: format_exception

Synchronizing and communicating between tasks
---------------------------------------------

.. autoclass:: Event
   :members:

.. autoclass:: Queue
   :members:

.. autoclass:: UnboundedQueue
   :members:

.. autoclass:: Semaphore
   :members:

.. autoclass:: Lock
   :members:

.. autoclass:: Condition
   :members:


Threads (if you must)
---------------------

In a perfect world, all third-party libraries and low-level APIs would
be natively async and integrated into Trio, and all would be happiness
and rainbows.

That world, alas, does not (yet) exist. Until it does, you may find
yourself needing to interact with non-Trio APIs that do uncouth things
like "blocking".

In acknowledgment of this reality, Trio provides two useful
capabilities for working with real, operating-system level,
:mod:`threading`\-module-style threads. First, if you're in Trio but
need to push some work into a thread, there's
:func:`run_in_worker_thread`. And if you're in a thread and need to
communicate back with trio, there's :func:`current_run_in_trio_thread`
and :func:`current_await_in_trio_thread`.


.. autofunction:: run_in_worker_thread

.. function:: current_run_in_trio_thread
              current_await_in_trio_thread

   Call these from inside a trio run to get a reference to the current
   run's :func:`run_in_trio_thread` or :func:`await_in_trio_thread`:

   .. function:: run_in_trio_thread(sync_fn, *args)
      :module:
   .. function:: await_in_trio_thread(async_fn, *args)
      :module:

   These functions schedule a call to ``sync_fn(*args)`` or ``await
   async_fn(*args)`` to happen in the main trio thread, wait for it to
   complete, and then return the result or raise whatever exception it
   raised.

   These are the *only* non-hazmat functions in trio that can be
   called from a different thread than the one that called
   :func:`trio.run`. These two functions *must* be called from a
   different thread than the one that called :func:`trio.run`. (After
   all, they're blocking functions!)

   :raises RunFinishedError: If the corresponding call to
      :func:`trio.run` has already completed.


This will probably be clearer with an example. Here we demonstrate how
to spawn a child thread::

   import trio
   import threading

   async def main():
       q = trio.Queue(1)

       await

   trio.run(main)


.. _instrumentation:

Debugging and instrumentation
-----------------------------

.. function:: current_statistics

Instrument API:

.. function:: current_instruments

.. autoclass:: trio.abc.Instrument
   :members:

Example::

   import time
   import warnings

   class WarnAboutLoopHogsInstrument:
       def __init__(self, threshold):
           self._threshold = threshold

       def before_task_step(self, task):
           self._start_time = time.perf_counter()

       def after_task_step(self, task):
           duration = time.perf_counter() - self._start_time
           if duration > threshold:
               warnings.warn(
                   "Task {} hogged the event loop for {} ms!"
                   .format(task, round(duration * 1000)))

Usage::

   trio.run(..., instruments=[WarnAboutLoopHogsInstrument(0.020)])

Other notes:

``Task.parent_task``

* current_tasks


Exceptions
----------

.. autoexception:: TrioInternalError

.. autoexception:: Cancelled

.. autoexception:: TooSlowError

.. autoexception:: WouldBlock

.. autoexception:: RunFinishedError
