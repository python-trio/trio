Testing made easier with ``trio.testing``
=========================================

.. module:: trio.testing

The :mod:`trio.testing` module provides various utilities to make it
easier to test Trio code. Unlike the other submodules in the
:mod:`trio` namespace, :mod:`trio.testing` is *not* automatically
imported when you do ``import trio``; you must ``import trio.testing``
explicitly.


Test harness integration
------------------------

.. decorator:: trio_test


.. _testing-time:

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

Regardless of these shenanigans, from "inside" Trio the passage of time
still seems normal so long as you restrict yourself to Trio's time
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


.. _testing-streams:

Streams
-------

Connecting to an in-process socket server
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. autofunction:: open_stream_to_socket_listener


.. _virtual-streams:

Virtual, controllable streams
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

One particularly challenging problem when testing network protocols is
making sure that your implementation can handle data whose flow gets
broken up in weird ways and arrives with weird timings: localhost
connections tend to be much better behaved than real networks, so if
you only test on localhost then you might get bitten later. To help
you out, Trio provides some fully in-memory implementations of the
stream interfaces (see :ref:`abstract-stream-api`), that let you write
all kinds of interestingly evil tests.

There are a few pieces here, so here's how they fit together:

:func:`memory_stream_pair` gives you a pair of connected,
bidirectional streams. It's like :func:`socket.socketpair`, but
without any involvement from that pesky operating system and its
networking stack.

To build a bidirectional stream, :func:`memory_stream_pair` uses
two unidirectional streams. It gets these by calling
:func:`memory_stream_one_way_pair`.

:func:`memory_stream_one_way_pair`, in turn, is implemented using the
low-ish level classes :class:`MemorySendStream` and
:class:`MemoryReceiveStream`. These are implementations of (you
guessed it) :class:`trio.abc.SendStream` and
:class:`trio.abc.ReceiveStream` that on their own, aren't attached to
anything – "sending" and "receiving" just put data into and get data
out of a private internal buffer that each object owns. They also have
some interesting hooks you can set, that let you customize the
behavior of their methods. This is where you can insert the evil, if
you want it. :func:`memory_stream_one_way_pair` takes advantage of
these hooks in a relatively boring way: it just sets it up so that
when you call ``send_all``, or when you close the send stream, then it
automatically triggers a call to :func:`memory_stream_pump`, which is
a convenience function that takes data out of a
:class:`MemorySendStream`\´s buffer and puts it into a
:class:`MemoryReceiveStream`\´s buffer. But that's just the default –
you can replace this with whatever arbitrary behavior you want.

Trio also provides some specialized functions for testing completely
**un**\buffered streams: :func:`lockstep_stream_one_way_pair` and
:func:`lockstep_stream_pair`. These aren't customizable, but they do
exhibit an extreme kind of behavior that's good at catching out edge
cases in protocol implementations.


API details
~~~~~~~~~~~

.. autoclass:: MemorySendStream
   :members:

.. autoclass:: MemoryReceiveStream
   :members:

.. autofunction:: memory_stream_pump

.. autofunction:: memory_stream_one_way_pair

.. autofunction:: memory_stream_pair

.. autofunction:: lockstep_stream_one_way_pair

.. autofunction:: lockstep_stream_pair


.. _testing-custom-streams:

Testing custom stream implementations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Trio also provides some functions to help you test your custom stream
implementations:

.. autofunction:: check_one_way_stream

.. autofunction:: check_two_way_stream

.. autofunction:: check_half_closeable_stream


.. _virtual-network-hooks:

Virtual networking for testing
------------------------------

In the previous section you learned how to use virtual in-memory
streams to test protocols that are written against Trio's
:class:`~trio.abc.Stream` abstraction. But what if you have more
complicated networking code – the kind of code that makes connections
to multiple hosts, or opens a listening socket, or sends UDP packets?

Trio doesn't itself provide a virtual in-memory network implementation
for testing – but :mod:`trio.socket` module does provide the hooks you
need to write your own! And if you're interested in helping implement
a reusable virtual network for testing, then `please get in touch
<https://github.com/python-trio/trio/issues/170>`__.

Note that these APIs are actually in :mod:`trio.socket` and
:mod:`trio.abc`, but we document them here because they're primarily
intended for testing.

.. currentmodule:: trio.socket

.. autofunction:: trio.socket.set_custom_hostname_resolver

.. currentmodule:: trio.abc

.. autoclass:: trio.abc.HostnameResolver
   :members:

.. currentmodule:: trio.socket

.. autofunction:: trio.socket.set_custom_socket_factory

.. currentmodule:: trio.abc

.. autoclass:: trio.abc.SocketFactory
   :members:

.. currentmodule:: trio.testing


Testing checkpoints
--------------------

.. autofunction:: assert_checkpoints
   :with:

.. autofunction:: assert_no_checkpoints
   :with:
