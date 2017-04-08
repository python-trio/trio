Testing made easier with ``trio.testing``
=========================================

.. module:: trio.testing

The :mod:`trio.testing` module provides various utilities to make it
easier to test trio code. Unlike the other submodules in the
:mod:`trio` namespace, :mod:`trio.testing` is *not* automatically
imported when you do ``import trio``; you must ``import trio.testing``
explicitly.


Test harness integration
------------------------

.. decorator:: trio_test


Time and timeouts
-----------------

:class:`trio.testing.MockClock` is a :class:`~trio.abc.Clock` with a
few tricks up its sleeve to help you efficiently test code involving
timeouts:

* By default, it starts at time 0, and clock time only advances when
  you explicitly call :meth:`~MockClock.jump`. This provides an
  extremely controllable clock for testing.

* You can set :attr:`~MockClock.rate` to 1.0 if you want it to start
  running in real time like a regular clock. You can stop and start
  the clock within a test. You can set :attr:`~MockClock.rate` to 10.0
  to make clock time pass at 10x real speed (so e.g. ``await
  trio.sleep(10)`` returns after 1 second).

* But even more interestingly, you can set
  :attr:`~MockClock.autojump_threshold` to zero or a small value, and
  then it will watch the execution of the run loop, and any time
  things have settled down and everyone's waiting for a timeout, it
  jumps the clock forward to that timeout. In many cases this allows
  natural-looking code involving timeouts to be automatically run at
  near full CPU utilization with no changes. (Thanks to `fluxcapacitor
  <https://github.com/majek/fluxcapacitor>`__ for this awesome idea.)

* And of course these can be mixed and matched at will.

Regardless of these shenanigans, from "inside" trio the passage of time
still seems normal so long as you restrict yourself to trio's time
functions (see :ref:`time-and-clocks`). Below is an example
demonstrating two different ways of making time pass quickly. Notice
how in both cases, the two tasks keep a consistent view of reality and
events happen in the expected order, despite being wildly divorced
from real time:

.. literalinclude:: reference-testing/across-realtime.py

Output:

.. literalinclude:: reference-testing/across-realtime.out
   :language: none

.. autoclass:: MockClock
   :members:


Inter-task ordering
-------------------

.. autoclass:: Sequencer

.. autofunction:: wait_all_tasks_blocked


Testing checkpoints
--------------------

.. autofunction:: assert_yields
   :with:

.. autofunction:: assert_no_yields
   :with:
