Trio reference manual
=====================

.. module:: trio

.. autofunction:: run

.. autoexception:: TrioInternalError


Timing, timeouts, and cancellation
----------------------------------

.. can't use autofunction for the auto-wrapped stuff, because they
   look like bound methods and sphinx.ext.autodoc can't handle that

.. function:: current_time

.. these are async...

.. asyncfunction:: foo()

.. autoasyncfunction:: sleep
.. autofunction:: sleep_until
.. autofunction:: sleep_forever

.. autoexception:: Cancelled

.. these are context managers...

.. autofunction:: open_cancel_scope

.. autofunction:: move_on_after

.. autofunction:: move_on_at

.. autofunction:: fail_after

.. autofunction:: fail_at

.. autoexception:: TooSlowError


Spawning and managing tasks
---------------------------

.. autofunction:: open_nursery

.. class:: Nursery

.. autoclass:: Task

.. autoexception:: MultiError
   :members:


Synchronization and inter-task communication
--------------------------------------------

.. autoclass:: Event
   :members:

.. autoexception:: WouldBlock

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


Threads
-------

Normally, trio applications use a single thread for

in particular, on CPython, `CPU-bound threads tend to "starve out"
IO-bound threads <https://bugs.python.org/issue7946>`__, so using
:func:`run_in_worker_thread` for CPU-bound work is likely to adversely
affect the main thread running trio. If you need to do this, you're
better off using a child process, or perhaps PyPy (which still has a
GIL, but may do a better job of fairly allocating CPU time between
threads).

.. autofunction:: run_in_worker_thread

Example::

   import trio
   import time

   async def main():
       # In real life, you'd use trio.sleep instead.
       # time.sleep stands in here for some blocking, IO-bound operation.
       await trio.run_in_worker_thread(time.sleep, 5)

   trio.run(main)

.. function:: current_run_in_trio_thread
.. function:: current_await_in_trio_thread

   Call these from inside a trio run to get a a reference to the
   current run's :func:`run_in_trio_thread` or
   :func:`await_in_trio_thread`:

.. function:: run_in_trio_thread(sync_fn, *args)
.. function:: await_in_trio_thread(async_fn, *args)

   These functions are not exposed as part of the ``trio`` namespace;
   you get them by calling :func:`current_run_in_trio_thread` or
   :func:`current_await_in_trio_thread`.

   These are the *only* functions in the ``trio.*`` namespace that can
   be called from a different thread than the one that called
   :func:`trio.run`. These two functions *must* be called from a
   different thread than the one that called :func:`trio.run` (after
   all, they're blocking functions!).

   Schedules a call to ``sync_fn(*args)`` or ``await async_fn(*args)``
   to happen in the trio thread, waits for it to complete, and then
   returns the result or raises

   If the corresponding call to :func:`trio.run` has already completed,
   then raises :exc:`RunFinishedError`.

.. autoexception:: RunFinishedError

   Raised if

This will probably be clearer with an example. Here we demonstrate how
to spawn a child thread::

   import trio
   import threading

   async def main():
       q = trio.Queue(1)

       await

   trio.run(main)



Debugging and instrumentation
-----------------------------

.. function:: current_statistics

Instrument API:

.. function:: current_instruments

.. class:: SampleInstrument

   .. method:: before_run()

      Called at the beginning of :func:`run`.

   .. method:: after_run()

      Called just before :func:`run` returns.

   .. method:: task_scheduled(task)

      Called when the given task becomes runnable.

   .. method:: before_task_step(task)

      Called immediately before we resume running the given task.

   .. method:: after_task_step(task)

      Called when we return to the main run loop after a task has
      yielded.

   .. method:: before_io_wait(timeout)

      Called before using the platform-specific

   .. method:: after_io_wait(timeout)


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


Stream API
----------

.. autoclass:: AsyncResource
   :members:

   .. asyncmethod:: foo()

.. autoclass:: SendStream
   :members:

.. autoclass:: RecvStream
   :members:

.. autoclass:: Stream
   :members:


Testing
-------
