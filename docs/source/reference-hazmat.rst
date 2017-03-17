=========================================
 Low-level operations in ``trio.hazmat``
=========================================

.. module:: trio.hazmat

.. warning::
   ⚠️ DANGER DANGER DANGER ⚠️

   You probably don't want to use this module.

The :mod:`trio.hazmat` API is public and stable (or at least, `as
stable as anything in trio is!
<https://github.com/python-trio/trio/issues/1>`__), but it has `nasty
big pointy teeth
<https://en.wikipedia.org/wiki/Rabbit_of_Caerbannog>`__. Mistakes may
not be handled gracefully; rules and conventions that are followed
strictly in the rest of trio do not always apply. Read and tread
carefully.

But if you find yourself needing to, for example, implement new
synchronization primitives or expose new low-level I/O functionality,
then you're in the right place.


Low-level I/O primitives
========================

Different environments expose different low-level APIs for performing
async I/O. :mod:`trio.hazmat` attempts to expose these APIs in a
relatively direct way, so as to allow maximum power and flexibility
for higher level code. However, this means that the exact API provided
may vary depending on what system trio is running on.


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
   :raises RuntimeError:
       if another task is already waiting for the given socket to
       become readable.

.. function:: wait_socket_writable(sock)
   :async:

   Block until the given :func:`socket.socket` object is writable.

   The given object *must* be exactly of type :func:`socket.socket`,
   nothing else.

   :raises TypeError:
       if the given object is not of type :func:`socket.socket`.
   :raises RuntimeError:
       if another task is already waiting for the given socket to
       become writable.


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
   :raises RuntimeError:
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
   :raises RuntimeError:
       if another task is already waiting for the given fd to
       become writable.


Kqueue-specific API
-------------------

TODO: these are currently more of a sketch than anything real. See
`#26 <https://github.com/python-trio/trio/issues/26>`__.

.. function:: current_kqueue()

.. function:: wait_kevent(ident, filter, abort_func)
   :async:

.. function:: monitor_kevent(ident, filter)
   :with: queue


Windows-specific API
--------------------

TODO: these are currently more of a sketch than anything real. See
`#26 <https://github.com/python-trio/trio/issues/26>`__ and `#52
<https://github.com/python-trio/trio/issues/52>`__.

.. function:: register_with_iocp(handle)

.. function:: wait_overlapped(handle, lpOverlapped)
   :async:

.. function:: current_iocp()

.. function:: monitor_completion_key()
   :with: queue


System tasks
============

.. autofunction:: spawn_system_task


Entering trio from external threads or signal handlers
======================================================

.. autofunction:: current_call_soon_thread_and_signal_safe


Safe KeyboardInterrupt handling
===============================

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

.. autofunction:: disable_ki_protection()
   :decorator:

   Decorator that marks the given regular function, generator
   function, async function, or async generator function as
   unprotected, i.e., the code inside this function *can* be rudely
   interrupted by :exc:`KeyboardInterrupt` at any moment.

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

.. autofunction:: enable_ki_protection()
   :decorator:

   Decorator that marks the given regular function, generator
   function, async function, or async generator function as
   unprotected, i.e., the code inside this function *won't* be rudely
   interrupted by :exc:`KeyboardInterrupt` at any moment. (Though if
   it contains any :ref:`check points <check-points>`, then it can
   still receive :exc:`KeyboardInterrupt` at those.)

   Be very careful to only use this decorator on functions that you
   know will run in bounded time.

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


Inserting check points
----------------------

.. autofunction:: yield_briefly

The next two functions are used *together* to make up a check point:

.. autofunction:: yield_if_cancelled
.. autofunction:: yield_briefly_no_cancel

These are commonly used in cases where we have an operation that
might-or-might-not block, and we want to implement trio's standard
check point semantics. Example::

   async def operation_that_maybe_blocks():
       await yield_if_cancelled()
       try:
           ret = attempt_operation()
       except BlockingIOError:
           # need to block and then retry, which we do below
           pass
       except:
           # some other error, finish the check point then let it propagate
           await yield_briefly_no_cancel()
           raise
       else:
           # operation succeeded, finish the check point then return
           await yield_briefly_no_cancel()
           return ret
       while True:
           await wait_for_operation_to_be_ready()
           try:
               return attempt_operation()
           except BlockingIOError:
               pass

This logic is a bit convoluted, but accomplishes all of the following:

* Every execution path passes through a check point (assuming that
  ``wait_for_operation_to_be_ready`` is an unconditional check point)

* Our :ref:`cancellation semantics <cancellable-primitives>` say that
  :exc:`~trio.Cancelled` should only be raised if the operation didn't
  happen. Using :func:`yield_briefly_no_cancel` on the early-exit
  branches accomplishes this.

* On the path where we do end up blocking, we don't pass through any
  schedule points before that, which avoids some unnecessary work.

* Avoids implicitly chaining the :exc:`BlockingIOError` with any
  errors raised by ``attempt_operation`` or
  ``wait_for_operation_to_be_ready``, by keeping the ``while True:``
  loop outside of the ``except BlockingIOError:`` block.

These functions can also be useful in other situations, e.g. if you're
going to call an uncancellable operation like
:func:`trio.run_in_worker_thread` or (potentially) overlapped I/O
operations on Windows, then you can call :func:`yield_if_cancelled`
first to make sure that the whole thing is a check point.


Low-level blocking
------------------

.. autoclass:: Abort
.. autofunction:: reschedule
.. autofunction:: yield_indefinitely

Here's an example lock class implemented using
:func:`yield_indefinitely` directly. This implementation has a number
of flaws, including lack of fairness, O(n) cancellation, missing error
checking, failure to insert a check point on the non-blocking path,
etc. If you really want to implement your own lock, then you should
study the implementation of :class:`trio.Lock` and use
:class:`ParkingLot`, which handles some of these issues for you. But
this does serve to illustrate the basic structure of the
:func:`yield_indefinitely` API::

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
               await trio.hazmat.yield_indefinitely(abort_fn)
           self._held = True

       def release(self):
           self._held = False
           if self._blocked_tasks:
               woken_task = self._blocked_tasks.popleft()
               trio.hazmat.reschedule(woken_task)
