Easier tests with ``trio.testing``
==================================

.. module:: trio.testing

The :mod:`trio.testing` module provides various utilities to make it
easier to write tests. Unlike the other submodules of the :mod:`trio`
namespace, :mod:`trio.testing` is *not* automatically imported when
you do ``import trio``; you must ``import trio.testing`` explicitly.

.. decorator:: trio_test

.. autofunction:: busy_wait_for

.. autofunction:: wait_run_loop_idle

.. autoclass:: MockClock

.. autofunction:: assert_yields
   :with:

.. autofunction:: assert_no_yields
   :with:

.. autoclass:: Sequencer
