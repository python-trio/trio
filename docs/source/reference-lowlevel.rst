=========================================================
 Introspecting and extending Trio with ``trio.lowlevel``
=========================================================

.. module:: trio.lowlevel

:mod:`trio.lowlevel` contains low-level APIs for introspecting and
extending Trio. If you're writing ordinary, everyday code, then you
can ignore this module completely. But sometimes you need something a
bit lower level. Here are some examples of situations where you should
reach for :mod:`trio.lowlevel`:

* You want to implement a new :ref:`synchronization primitive
  <synchronization>` that Trio doesn't (yet) provide, like a
  reader-writer lock.
* You want to extract low-level metrics to monitor the health of your
  application.
* You want to use a low-level operating system interface that Trio
  doesn't (yet) provide its own wrappers for, like watching a
  filesystem directory for changes.
* You want to implement an interface for calling between Trio and
  another event loop within the same process.
* You're writing a debugger and want to visualize Trio's task tree.
* You need to interoperate with a C library whose API exposes raw file
  descriptors.

You don't need to be scared of :mod:`trio.lowlevel`, as long as you
take proper precautions. These are real public APIs, with strictly
defined and carefully documented semantics. They're the same tools we
use to implement all the nice high-level APIs in the :mod:`trio`
namespace. But, be careful. Some of those strict semantics have `nasty
big pointy teeth
<https://en.wikipedia.org/wiki/Rabbit_of_Caerbannog>`__. If you make a
mistake, Trio may not be able to handle it gracefully; conventions and
guarantees that are followed strictly in the rest of Trio do not
always apply. When you use this module, it's your job to think about
how you're going to handle the tricky cases so you can expose a
friendly Trio-style API to your users.


Debugging and instrumentation
=============================

Trio tries hard to provide useful hooks for debugging and
instrumentation. Some are documented above (the nursery introspection
attributes, :meth:`trio.Lock.statistics`, etc.). Here are some more.


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

Since this hooks into Trio at a rather low level, you do have to be
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
Trio's internal scheduling decisions.


Low-level I/O primitives
========================

Different environments expose different low-level APIs for performing
async I/O. :mod:`trio.lowlevel` exposes these APIs in a relatively
direct way, so as to allow maximum power and flexibility for higher
level code. However, this means that the exact API provided may vary
depending on what system Trio is running on.


Universally available API
-------------------------

All environments provide the following functions:

.. function:: wait_readable(obj)
   :async:

   Block until the kernel reports that the given object is readable.

   On Unix systems, ``obj`` must either be an integer file descriptor,
   or else an object with a ``.fileno()`` method which returns an
   integer file descriptor. Any kind of file descriptor can be passed,
   though the exact semantics will depend on your kernel. For example,
   this probably won't do anything useful for on-disk files.

   On Windows systems, ``obj`` must either be an integer ``SOCKET``
   handle, or else an object with a ``.fileno()`` method which returns
   an integer ``SOCKET`` handle. File descriptors aren't supported,
   and neither are handles that refer to anything besides a
   ``SOCKET``.

   :raises trio.BusyResourceError:
       if another task is already waiting for the given socket to
       become readable.
   :raises trio.ClosedResourceError:
       if another task calls :func:`notify_closing` while this
       function is still working.

.. function:: wait_writable(obj)
   :async:

   Block until the kernel reports that the given object is writable.

   See `wait_readable` for the definition of ``obj``.

   :raises trio.BusyResourceError:
       if another task is already waiting for the given socket to
       become writable.
   :raises trio.ClosedResourceError:
       if another task calls :func:`notify_closing` while this
       function is still working.


.. function:: notify_closing(obj)

   Call this before closing a file descriptor (on Unix) or socket (on
   Windows). This will cause any `wait_readable` or `wait_writable`
   calls on the given object to immediately wake up and raise
   `~trio.ClosedResourceError`.

   This doesn't actually close the object – you still have to do that
   yourself afterwards. Also, you want to be careful to make sure no
   new tasks start waiting on the object in between when you call this
   and when it's actually closed. So to close something properly, you
   usually want to do these steps in order:

   1. Explicitly mark the object as closed, so that any new attempts
      to use it will abort before they start.
   2. Call `notify_closing` to wake up any already-existing users.
   3. Actually close the object.

   It's also possible to do them in a different order if that's more
   convenient, *but only if* you make sure not to have any checkpoints in
   between the steps. This way they all happen in a single atomic
   step, so other tasks won't be able to tell what order they happened
   in anyway.


Unix-specific API
-----------------

`FdStream` supports wrapping Unix files (such as a pipe or TTY) as
a stream.

If you have two different file descriptors for sending and receiving,
and want to bundle them together into a single bidirectional
`~trio.abc.Stream`, then use `trio.StapledStream`::

    bidirectional_stream = trio.StapledStream(
        trio.lowlevel.FdStream(write_fd),
        trio.lowlevel.FdStream(read_fd)
    )

.. autoclass:: FdStream
   :show-inheritance:
   :members:


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

.. function:: WaitForSingleObject(handle)
    :async:
    
    Async and cancellable variant of `WaitForSingleObject
    <https://msdn.microsoft.com/en-us/library/windows/desktop/ms687032(v=vs.85).aspx>`__.
    Windows only.
    
    :arg handle:
        A Win32 object handle, as a Python integer.
    :raises OSError:
        If the handle is invalid, e.g. when it is already closed.


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


Global state: system tasks and run-local variables
==================================================

.. autoclass:: RunVar

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
   like :func:`trio.from_thread.run`, which uses
   :meth:`TrioToken.run_sync_soon` to get into the Trio
   thread. :meth:`~TrioToken.run_sync_soon` callbacks are run with
   :exc:`KeyboardInterrupt` protection enabled, and
   :func:`trio.from_thread.run` takes advantage of this to safely set up
   the machinery for sending a response back to the original thread, but
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
might-or-might-not block, and you want to implement Trio's standard
checkpoint semantics. Example::

   async def operation_that_maybe_blocks():
       await checkpoint_if_cancelled()
       try:
           ret = attempt_operation()
       except BlockingIOError:
           # need to block and then retry, which we do below
           pass
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

* Every successful execution path passes through a checkpoint (assuming that
  ``wait_for_operation_to_be_ready`` is an unconditional checkpoint)

* Our :ref:`cancellation semantics <cancellable-primitives>` say that
  :exc:`~trio.Cancelled` should only be raised if the operation didn't
  happen. Using :func:`cancel_shielded_checkpoint` on the early-exit
  branch accomplishes this.

* On the path where we do end up blocking, we don't pass through any
  schedule points before that, which avoids some unnecessary work.

* Avoids implicitly chaining the :exc:`BlockingIOError` with any
  errors raised by ``attempt_operation`` or
  ``wait_for_operation_to_be_ready``, by keeping the ``while True:``
  loop outside of the ``except BlockingIOError:`` block.

These functions can also be useful in other situations. For example,
when :func:`trio.to_thread.run_sync` schedules some work to run in a
worker thread, it blocks until the work is finished (so it's a
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
                   return trio.lowlevel.Abort.SUCCEEDED
               await trio.lowlevel.wait_task_rescheduled(abort_fn)
           self._held = True

       def release(self):
           self._held = False
           if self._blocked_tasks:
               woken_task = self._blocked_tasks.popleft()
               trio.lowlevel.reschedule(woken_task)


Task API
--------

.. autofunction:: current_root_task()

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

   .. attribute:: context

      This task's :class:`contextvars.Context` object.

   .. autoattribute:: parent_nursery

   .. autoattribute:: child_nurseries

   .. attribute:: custom_sleep_data

      Trio doesn't assign this variable any meaning, except that it
      sets it to ``None`` whenever a task is rescheduled. It can be
      used to share data between the different tasks involved in
      putting a task to sleep and then waking it up again. (See
      :func:`wait_task_rescheduled` for details.)


.. _live-coroutine-handoff:

Handing off live coroutine objects between coroutine runners
------------------------------------------------------------

Internally, Python's async/await syntax is built around the idea of
"coroutine objects" and "coroutine runners". A coroutine object
represents the state of an async callstack. But by itself, this is
just a static object that sits there. If you want it to do anything,
you need a coroutine runner to push it forward. Every Trio task has an
associated coroutine object (see :data:`Task.coro`), and the Trio
scheduler acts as their coroutine runner.

But of course, Trio isn't the only coroutine runner in Python –
:mod:`asyncio` has one, other event loops have them, you can even
define your own.

And in some very, very unusual circumstances, it even makes sense to
transfer a single coroutine object back and forth between different
coroutine runners. That's what this section is about. This is an
*extremely* exotic use case, and assumes a lot of expertise in how
Python async/await works internally. For motivating examples, see
`trio-asyncio issue #42
<https://github.com/python-trio/trio-asyncio/issues/42>`__, and `trio
issue #649 <https://github.com/python-trio/trio/issues/649>`__. For
more details on how coroutines work, we recommend André Caron's `A
tale of event loops
<https://github.com/AndreLouisCaron/a-tale-of-event-loops>`__, or
going straight to `PEP 492
<https://www.python.org/dev/peps/pep-0492/>`__ for the full details.

.. autofunction:: permanently_detach_coroutine_object

.. autofunction:: temporarily_detach_coroutine_object

.. autofunction:: reattach_detached_coroutine_object
