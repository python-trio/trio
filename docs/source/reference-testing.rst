Testing made easier with ``trio.testing``
=========================================

.. module:: trio.testing

The :mod:`trio.testing` module provides various utilities to make it
easier to test trio code. Unlike the other submodules in the
:mod:`trio` namespace, :mod:`trio.testing` is *not* automatically
imported when you do ``import trio``; you must ``import trio.testing``
explicitly.

.. decorator:: trio_test

.. autoclass:: MockClock

.. autoclass:: Sequencer

.. autofunction:: assert_yields
   :with:

.. autofunction:: assert_no_yields
   :with:

.. autofunction:: wait_all_tasks_blocked

.. autofunction:: busy_wait_for
