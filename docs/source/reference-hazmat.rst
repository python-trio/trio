=======================================================
 Introspecting and extending Trio with ``trio.hazmat``
=======================================================

.. module:: trio.hazmat

.. warning::
   You probably don't want to use this module.

:mod:`trio.hazmat` is Trio's "hazardous materials" layer: it contains
APIs useful for introspecting and extending Trio. If you're writing
ordinary, everyday code, then you can ignore this module completely.
But sometimes you need something a bit lower level. Here are some
examples of situations where you should reach for :mod:`trio.hazmat`:

* You want to implement a new :ref:`synchronization primitive
  <synchronization>` that Trio doesn't (yet) provide, like a
  reader-writer lock.
* You want to extract low-level metrics to monitor the health of your
  application.
* You want to add support for a low-level operating system interface
  that Trio doesn't (yet) expose, like watching a filesystem directory
  for changes.
* You want to implement an interface for calling between Trio and
  another event loop within the same process.
* You're writing a debugger and want to visualize Trio's task tree.
* You need to interoperate with a C library whose API exposes raw file
  descriptors.

Using :mod:`trio.hazmat` isn't really *that* hazardous; in fact you're
already using it – it's how most of the functionality described in
previous chapters is implemented. The APIs described here have
strictly defined and carefully documented semantics, and are perfectly
safe – *if* you read carefully and take proper precautions. Some of
those strict semantics have `nasty big pointy teeth
<https://en.wikipedia.org/wiki/Rabbit_of_Caerbannog>`__. If you make a
mistake, Trio may not be able to handle it gracefully; conventions and
guarantees that are followed strictly in the rest of Trio do not
always apply. Using this module makes it your responsibility to think
through and handle the nasty cases to expose a friendly Trio-style API
to your users.


Debugging and instrumentation
=============================

Trio tries hard to provide useful hooks for debugging and
instrumentation. Some are documented above (the nursery introspection
attributes, :meth:`trio.Queue.statistics`, etc.). Here are some more.


Global statistics
-----------------

.. autofunction:: current_statistics


The current clock
-----------------

.. autofunction:: current_clock


.. _instrumentation:

Instrument API
--------------

The instrument API provides a standard way to add custom
instrumentation to the run loop. Want to make a histogram of
scheduling latencies, log a stack trace of any task that blocks the
run loop for >50 ms, or measure what percentage of your process's
running time is spent waiting for I/O? This is the place.

The general idea is that at any given moment, :func:`trio.run`
maintains a set of "instruments", which are objects that implement the
:class:`trio.abc.Instrument` interface. When an interesting event
happens, it loops over these instruments and notifies them by calling
an appropriate method. The tutorial has :ref:`a simple example of
using this for tracing <tutorial-instrument-example>`.

Since this hooks into trio at a rather low level, you do have to be
careful. The callbacks are run synchronously, and in many cases if
they error out then there isn't any plausible way to propagate this
exception (for instance, we might be deep in the guts of the exception
propagation machinery...). Therefore our `current strategy
<https://github.com/python-trio/trio/issues/47>`__ for handling
exceptions raised by instruments is to (a) log an exception to the
``"trio.abc.Instrument"`` logger, which by default prints a stack
trace to standard error and (b) disable the offending instrument.

You can register an initial list of instruments by passing them to
:func:`trio.run`. :func:`add_instrument` and
:func:`remove_instrument` let you add and remove instruments at
runtime.

.. autofunction:: add_instrument

.. autofunction:: remove_instrument

And here's the interface to implement if you want to build your own
:class:`~trio.abc.Instrument`:

.. autoclass:: trio.abc.Instrument
   :members:

The tutorial has a :ref:`fully-worked example
<tutorial-instrument-example>` of defining a custom instrument to log
trio's internal scheduling decisions.


Low-level I/O primitives
========================

Different environments expose different low-level APIs for performing
async I/O. :mod:`trio.hazmat` exposes these APIs in a relatively
direct way, so as to allow maximum power and flexibility for higher
level code. However, this means that the exact API provided may vary
depending on what system trio is running on.


Universally available API
-------------------------

All environments provide the following functions:

.. function:: wait_socket_readable(sock)
   :async:

   Block until the given :func:`socket.socket` object is readable.

   The given object *must* be exactly of type :func:`socket.socket`,
   nothing else.

   :raises TypeError:
       if the given object is not of type :func:`socket.socket`.
   :raises trio.ResourceBusyError:
       if another task is already waiting for the given socket to
       become readable.

.. function:: wait_socket_writable(sock)
   :async:

   Block until the given :func:`socket.socket` object is writable.

   The given object *must* be exactly of type :func:`socket.socket`,
   nothing else.

   :raises TypeError:
       if the given object is not of type :func:`socket.socket`.
   :raises trio.ResourceBusyError:
       if another task is already waiting for the given socket to
       become writable.

In addition, :mod:`trio.hazmat` contains low-level stream adapters for
OS file handles. You can use them to trio-ize standard input or output. Be
aware that there is no provision for text encoding yet, which is why
they're in `trio.hazmat`.

.. autoclass:: ReadFDStream

.. autoclass:: WriteFDStream

Unix-specific API
-----------------

Unix-like systems provide the following functions:

.. function:: wait_readable(fd)
   :async:

   Block until the given file descriptor is readable.

   .. warning::

      This is "readable" according to the operating system's
      definition of readable. In particular, it probably won't tell
      you anything useful for on-disk files.

   :arg fd:
       integer file descriptor, or else an object with a ``fileno()`` method
   :raises trio.ResourceBusyError:
       if another task is already waiting for the given fd to
       become readable.


.. function:: wait_writable(fd)
   :async:

   Block until the given file descriptor is writable.

   .. warning::

      This is "writable" according to the operating system's
      definition of writable. In particular, it probably won't tell
      you anything useful for on-disk files.

   :arg fd:
       integer file descriptor, or else an object with a ``fileno()`` method
   :raises trio.ResourceBusyError:
       if another task is already waiting for the given fd to
       become writable.


Kqueue-specific API
-------------------

TODO: these are implemented, but are currently more of a sketch than
anything real. See `#26
<https://github.com/python-trio/trio/issues/26>`__.

.. function:: current_kqueue()

.. function:: wait_kevent(ident, filter, abort_func)
   :async:

.. function:: monitor_kevent(ident, filter)
   :with: queue


Windows-specific API
--------------------

TODO: these are implemented, but are currently more of a sketch than
anything real. See `#26
<https://github.com/python-trio/trio/issues/26>`__ and `#52
<https://github.com/python-trio/trio/issues/52>`__.

.. function:: register_with_iocp(handle)

.. function:: wait_overlapped(handle, lpOverlapped)
   :async:

.. function:: current_iocp()

.. function:: monitor_completion_key()
   :with: queue


Unbounded queues
================

In the section :ref:`queue`, we showed an example with two producers
and one consumer using the same queue, where the queue size would grow
without bound to produce unbounded latency and memory usage.
:class:`trio.Queue` avoids this by placing an upper bound on how big
the queue can get before ``put`` starts blocking. But what if you're
in a situation where ``put`` can't block?

There is another option: the queue consumer could get greedy. Each
time it runs, it could eagerly consume all of the pending items before
allowing another task to run. (In some other systems, this would
happen automatically because their queue's ``get`` method doesn't
invoke the scheduler unless it has to block. But :ref:`in trio, get is
always a checkpoint <checkpoint-rule>`.) This works, but it's a bit
risky: basically instead of applying backpressure to specifically the
producer tasks, we're applying it to *all* the tasks in our system.
The danger here is that if enough items have built up in the queue,
then "stopping the world" to process them all may cause unacceptable
latency spikes in unrelated tasks. Nonetheless, this is still the
right choice in situations where it's impossible to apply backpressure
more precisely. So this is the strategy implemented by
:class:`UnboundedQueue`. The main time you should use this is when
working with low-level APIs like :func:`monitor_kevent`.

.. autoclass:: UnboundedQueue
   :members:


Global state: system tasks and run-local storage
================================================

.. autoclass:: RunLocal

.. autofunction:: spawn_system_task


Trio tokens
===========

.. autoclass:: TrioToken()
   :members:

.. autofunction:: current_trio_token


Safer KeyboardInterrupt handling
================================

Trio's handling of control-C is designed to balance usability and
safety. On the one hand, there are sensitive regions (like the core
scheduling loop) where it's simply impossible to handle arbitrary
:exc:`KeyboardInterrupt` exceptions while maintaining our core
correctness invariants. On the other, if the user accidentally writes
an infinite loop, we do want to be able to break out of that. Our
solution is to install a default signal handler which checks whether
it's safe to raise :exc:`KeyboardInterrupt` at the place where the
signal is received. If so, then we do; otherwise, we schedule a
:exc:`KeyboardInterrupt` to be delivered to the main task at the next
available opportunity (similar to how :exc:`~trio.Cancelled` is
delivered).

So that's great, but – how do we know whether we're in one of the
sensitive parts of the program or not?

This is determined on a function-by-function basis. By default, a
function is protected if its caller is, and not if its caller isn't;
this is helpful because it means you only need to override the
defaults at places where you transition from protected code to
unprotected code or vice-versa.

These transitions are accomplished using two function decorators:

.. function:: disable_ki_protection()
   :decorator:

   Decorator that marks the given regular function, generator
   function, async function, or async generator function as
   unprotected against :exc:`KeyboardInterrupt`, i.e., the code inside
   this function *can* be rudely interrupted by
   :exc:`KeyboardInterrupt` at any moment.

   If you have multiple decorators on the same function, then this
   should be at the bottom of the stack (closest to the actual
   function).

   An example of where you'd use this is in implementing something
   like ``run_in_trio_thread``, which uses
   ``call_soon_thread_and_signal_safe`` to get into the trio
   thread. ``call_soon_thread_and_signal_safe`` callbacks are run with
   :exc:`KeyboardInterrupt` protection enabled, and
   ``run_in_trio_thread`` takes advantage of this to safely set up the
   machinery for sending a response back to the original thread, and
   then uses :func:`disable_ki_protection` when entering the
   user-provided function.

.. function:: enable_ki_protection()
   :decorator:

   Decorator that marks the given regular function, generator
   function, async function, or async generator function as protected
   against :exc:`KeyboardInterrupt`, i.e., the code inside this
   function *won't* be rudely interrupted by
   :exc:`KeyboardInterrupt`. (Though if it contains any
   :ref:`checkpoints <checkpoints>`, then it can still receive
   :exc:`KeyboardInterrupt` at those. This is considered a polite
   interruption.)

   .. warning::

      Be very careful to only use this decorator on functions that you
      know will either exit in bounded time, or else pass through a
      checkpoint regularly. (Of course all of your functions should
      have this property, but if you mess it up here then you won't
      even be able to use control-C to escape!)

   If you have multiple decorators on the same function, then this
   should be at the bottom of the stack (closest to the actual
   function).

   An example of where you'd use this is on the ``__exit__``
   implementation for something like a :class:`~trio.Lock`, where a
   poorly-timed :exc:`KeyboardInterrupt` could leave the lock in an
   inconsistent state and cause a deadlock.

.. autofunction:: currently_ki_protected


Result objects
==============

Trio provides some simple classes for representing the result of a
Python function call, so that it can be passed around. The basic rule
is::

    result = Result.capture(f, *args)
    x = result.unwrap()

is the same as::

    x = f(*args)

even if ``f`` raises an error. And there's also
:meth:`Result.acapture`, which is like ``await f(*args)``.

There's nothing really dangerous about this system – it's actually
very general and quite handy! But mostly it's used for things like
implementing :func:`trio.run_sync_in_worker_thread`, or for getting
values to pass to :func:`reschedule`, so we put it in
:mod:`trio.hazmat` to avoid cluttering up the main API.

Since :class:`Result` objects are simple immutable data structures
that don't otherwise interact with the trio machinery, it's safe to
create and access :class:`Result` objects from any thread you like.

.. autoclass:: Result
   :members:

.. autoclass:: Value
   :members:

.. autoclass:: Error
   :members:


Sleeping and waking
===================

Wait queue abstraction
----------------------

.. autoclass:: ParkingLot
   :members:
   :undoc-members:


Low-level checkpoint functions
------------------------------

.. autofunction:: checkpoint

The next two functions are used *together* to make up a checkpoint:

.. autofunction:: checkpoint_if_cancelled
.. autofunction:: cancel_shielded_checkpoint

These are commonly used in cases where you have an operation that
might-or-might-not block, and you want to implement trio's standard
checkpoint semantics. Example::

   async def operation_that_maybe_blocks():
       await checkpoint_if_cancelled()
       try:
           ret = attempt_operation()
       except BlockingIOError:
           # need to block and then retry, which we do below
           pass
       except:
           # some other error, finish the checkpoint then let it propagate
           await cancel_shielded_checkpoint()
           raise
       else:
           # operation succeeded, finish the checkpoint then return
           await cancel_shielded_checkpoint()
           return ret
       while True:
           await wait_for_operation_to_be_ready()
           try:
               return attempt_operation()
           except BlockingIOError:
               pass

This logic is a bit convoluted, but accomplishes all of the following:

* Every execution path passes through a checkpoint (assuming that
  ``wait_for_operation_to_be_ready`` is an unconditional checkpoint)

* Our :ref:`cancellation semantics <cancellable-primitives>` say that
  :exc:`~trio.Cancelled` should only be raised if the operation didn't
  happen. Using :func:`cancel_shielded_checkpoint` on the early-exit
  branches accomplishes this.

* On the path where we do end up blocking, we don't pass through any
  schedule points before that, which avoids some unnecessary work.

* Avoids implicitly chaining the :exc:`BlockingIOError` with any
  errors raised by ``attempt_operation`` or
  ``wait_for_operation_to_be_ready``, by keeping the ``while True:``
  loop outside of the ``except BlockingIOError:`` block.

These functions can also be useful in other situations. For example,
when :func:`trio.run_sync_in_worker_thread` schedules some work to run
in a worker thread, it blocks until the work is finished (so it's a
schedule point), but by default it doesn't allow cancellation. So to
make sure that the call always acts as a checkpoint, it calls
:func:`checkpoint_if_cancelled` before starting the thread.


Low-level blocking
------------------

.. autofunction:: wait_task_rescheduled
.. autoclass:: Abort
.. autofunction:: reschedule

Here's an example lock class implemented using
:func:`wait_task_rescheduled` directly. This implementation has a
number of flaws, including lack of fairness, O(n) cancellation,
missing error checking, failure to insert a checkpoint on the
non-blocking path, etc. If you really want to implement your own lock,
then you should study the implementation of :class:`trio.Lock` and use
:class:`ParkingLot`, which handles some of these issues for you. But
this does serve to illustrate the basic structure of the
:func:`wait_task_rescheduled` API::

   class NotVeryGoodLock:
       def __init__(self):
           self._blocked_tasks = collections.deque()
           self._held = False

       async def acquire(self):
           while self._held:
               task = trio.current_task()
               self._blocked_tasks.append(task)
               def abort_fn(_):
                   self._blocked_tasks.remove(task)
                   return trio.hazmat.Abort.SUCCEEDED
               await trio.hazmat.wait_task_rescheduled(abort_fn)
           self._held = True

       def release(self):
           self._held = False
           if self._blocked_tasks:
               woken_task = self._blocked_tasks.popleft()
               trio.hazmat.reschedule(woken_task)


Task API
--------

.. autofunction:: current_task()

.. class:: Task()

   A :class:`Task` object represents a concurrent "thread" of
   execution. It has no public constructor; Trio internally creates a
   :class:`Task` object for each call to ``nursery.start(...)`` or
   ``nursery.start_soon(...)``.

   Its public members are mostly useful for introspection and
   debugging:

   .. attribute:: name

      String containing this :class:`Task`\'s name. Usually the name
      of the function this :class:`Task` is running, but can be
      overridden by passing ``name=`` to ``start`` or ``start_soon``.

   .. attribute:: coro

      This task's coroutine object. Example usage: extracting a stack
      trace::

          import traceback

          def walk_coro_stack(coro):
              while coro is not None:
                  if hasattr(coro, "cr_frame"):
                      # A real coroutine
                      yield coro.cr_frame, coro.cr_frame.f_lineno
                      coro = coro.cr_await
                  else:
                      # A generator decorated with @types.coroutine
                      yield coro.gi_frame, coro.gi_frame.f_lineno
                      coro = coro.gi_yieldfrom

          def print_stack_for_task(task):
              ss = traceback.StackSummary.extract(walk_coro_stack(task.coro))
              print("".join(ss.format()))

   .. autoattribute:: parent_nursery

   .. autoattribute:: child_nurseries

