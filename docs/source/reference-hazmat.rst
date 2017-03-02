Low-level operations in ``trio.hazmat``
=======================================

DANGER DANGER DANGER

You probably don't want this module.

The API defined here is public and stable (at least as much as
anything in trio is stable given it's pre-1.0 status), but it has
`nasty big pointy teeth
<https://en.wikipedia.org/wiki/Rabbit_of_Caerbannog>`__.

.. module:: trio.hazmat

Low-level I/O primitives
------------------------

.. function:: wait_socket_readable
.. function:: wait_socket_writable

.. function:: wait_readable
.. function:: wait_writable


Kqueue-specific API
~~~~~~~~~~~~~~~~~~~

.. function:: current_kqueue
.. function:: wait_kevent(ident, filter, abort_func)
.. function:: monitor_kevent


Windows-specific API
~~~~~~~~~~~~~~~~~~~~

.. function:: register_with_iocp
.. function:: wait_overlapped
.. function:: current_iocp
.. function:: monitor_completion_key


Entering trio from external threads or signal handlers
------------------------------------------------------

.. autofunction:: current_call_soon_thread_and_signal_safe


Safe handling of KeyboardInterrupt
----------------------------------

.. decorator:: disable_ki_protection
.. decorator:: enable_ki_protection
.. autofunction:: currently_ki_protected


System tasks
------------

.. autofunction:: spawn_system_task


Sleeping and waking
-------------------

Wait queue abstraction
~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: ParkingLot
   :members:
   :undoc-members:


Inserting yield points
~~~~~~~~~~~~~~~~~~~~~~

.. autofunction:: yield_briefly

.. autofunction:: yield_if_cancelled
.. autofunction:: yield_briefly_no_cancel

These two functions *together* make up a yield point. They're commonly
used in cases where we have an operation that might-or-might-not
block, like::

   async def maybe_blocks():
       await yield_if_cancelled()
       try:
           ret = attempt_operation()
       except BlockingIOError:
           # need to block and then retry
           while True:
               await wait_for_operation_to_be_ready()
               try:
                   return attempt_operation()
               except BlockingIOError:
                   pass
       except:
           # some other error, finish the yield point then let it propagate
           await yield_briefly_no_cancel()
       else:
           # operation succeeded, finish the yield point then return
           await yield_briefly_no_cancel()
           return ret


Blocking
~~~~~~~~

.. autoclass:: Abort
.. autofunction:: reschedule
.. autofunction:: yield_indefinitely

