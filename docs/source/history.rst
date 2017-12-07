Release history
===============

.. currentmodule:: trio

.. towncrier release notes start

Trio 0.2.0 (2017-12-06)
-----------------------

Trio 0.2.0 contains changes from 14 contributors, and brings major new
features and bug fixes, as well as a number of deprecations and a very
small number of backwards incompatible changes. We anticipate that
these should be easy to adapt to, but make sure to read about them
below, and if you're using Trio then remember to `read and subscribe
to issue #1 <https://github.com/python-trio/trio/issues/1>`__.


Highlights
~~~~~~~~~~

* Added a comprehensive API for async filesystem I/O: see
  :ref:`async-file-io` (`gh-20
  <https://github.com/python-trio/trio/pull/20>`__)

* The new nursery :meth:`~The nursery interface.start` method makes it
  easy to perform controlled start-up of long-running tasks. For
  example, given an appropriate ``http_server_on_random_open_port``
  function, you could write::

      port = await nursery.start(http_server_on_random_open_port)

  and this would start the server running in the background in the
  nursery, and then give you back the random port it selected – but
  not until it had finished initializing and was ready to accept
  requests!

* Added a :ref:`new abstract API for byte streams
  <abstract-stream-api>`, and :mod:`trio.testing` gained helpers for
  creating fake streams for :ref:`testing your protocol implementation
  <virtual-streams>` and checking that your custom stream
  implementation :ref:`follows the stream contract
  <testing-custom-streams>`.

* If you're currently using :mod:`trio.socket` then you should
  :ref:`switch to using our new high-level networking API instead
  <high-level-networking>`. It takes care of many tiresome details, it's
  fully integrated with the abstract stream API, and it provides
  niceties like a state-of-the-art `Happy Eyeballs implementation
  <https://en.wikipedia.org/wiki/Happy_Eyeballs>`__ in
  :func:`open_tcp_stream` and server helpers that integrate with
  ``nursery.start``.

* We've also added comprehensive support for SSL/TLS encryption,
  including SNI (both client and server side), STARTTLS, renegotiation
  during full-duplex usage (subject to OpenSSL limitations), and
  applying encryption to arbitrary :class:`~trio.abc.Stream`\s, which
  allows for interesting applications like `TLS-over-TLS
  <https://daniel.haxx.se/blog/2016/11/26/https-proxy-with-curl/>`__.
  See: :func:`trio.open_ssl_over_tcp_stream`,
  :func:`trio.serve_ssl_over_tcp`,
  :func:`trio.open_ssl_over_tcp_listeners`, and :mod:`trio.ssl`.

  Interesting fact: the test suite for :mod:`trio.ssl` has so far
  found bugs in CPython's ssl module, PyPy's ssl module, PyOpenSSL,
  and OpenSSL. (:mod:`trio.ssl` doesn't use PyOpenSSL.) Trio's test
  suite is fairly thorough.

* You know thread-local storage? Well, Trio now has an equivalent:
  :ref:`task-local storage <task-local-storage>`. There's also the
  related, but more obscure, run-local storage; see
  :class:`~trio.hazmat.RunLocal`. (`#2
  <https://github.com/python-trio/trio/pull/2>`__)

* Added a new :ref:`guide to for contributors <contributing>`.


Breaking changes and deprecations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Trio is a young and ambitious project, but it also aims to become a
stable, production-quality foundation for async I/O in Python.
Therefore, our approach for now is to provide deprecation warnings
where-ever possible, but on a fairly aggressive cycle as we push
towards stability. If you use Trio you should `read and subscribe to
issue #1 <https://github.com/python-trio/trio/issues/1>`__. We'd also
welcome feedback on how this approach is working, whether our
deprecation warnings could be more helpful, or anything else.

The tl;dr is: stop using ``socket.bind`` if you can, and then fix
everything your test suite warns you about.

Upcoming breaking changes without warnings (i.e., stuff that works in
0.2.0, but won't work in 0.3.0):

* In the next release, the ``bind`` method on Trio socket objects will
  become async (`#241
  <https://github.com/python-trio/trio/issues/241>`__). Unfortunately,
  there's no good way to provide a warning here. We recommend
  switching to the new highlevel networking APIs like
  :func:`serve_tcp`, which will insulate you from this change.

Breaking changes (i.e., stuff that could theoretically break a program
that worked on 0.1.0):

* :mod:`trio.socket` no longer attempts to normalize or modernize
  socket options across different platforms. The high-level networking
  API now handles that, freeing :mod:`trio.socket` to focus on giving
  you raw, unadulterated BSD sockets.

* When a socket ``sendall`` call was cancelled, it used to attach some
  metadata to the exception reporting how much data was actually sent.
  It no longer does this, because in common configurations like an
  :class:`~trio.ssl.SSLStream` wrapped around a
  :class:`~trio.SocketStream` it becomes ambiguous which "level" the
  partial metadata applies to, leading to confusion and bugs. There is
  no longer any way to tell how much data was sent after a ``sendall``
  is cancelled.

* The :func:`trio.socket.getprotobyname` function is now async, like
  it should have been all along. I doubt anyone will ever use it, but
  that's no reason not to get the details right.

* The :mod:`trio.socket` functions ``getservbyport``,
  ``getservbyname``, and ``getfqdn`` have been removed, because they
  were obscure, buggy, and obsolete. Use
  :func:`~trio.socket.getaddrinfo` instead.

Upcoming breaking changes with warnings (i.e., stuff that in 0.2.0
*will* work but will print loud complaints, and that won't work in
0.3.0):

* For consistency with the new ``start`` method, the nursery ``spawn``
  method is being renamed to ``start_soon`` (`#284
  <https://github.com/python-trio/trio/issues/284>`__)

* ``trio.socket.sendall`` is deprecated; use ``trio.open_tcp_stream``
  and ``SocketStream.send_all`` instead (`#291
  <https://github.com/python-trio/trio/issues/291>`__)

* Trio now consistently uses ``run`` for functions that take and run
  an async function (like :func:`trio.run`!), and ``run_sync`` for
  functions that take and run a synchronous function. As part of this:

  * ``run_in_worker_thread`` is becoming
    :func:`run_sync_in_worker_thread`

  * We took the opportunity to refactor ``run_in_trio_thread`` and
    ``await_in_trio_thread`` into the new class
    :class:`trio.BlockingTrioPortal`

  * The hazmat function ``current_call_soon_thread_and_signal_safe``
    is being replaced by :class:`trio.hazmat.TrioToken`

  See `#68 <https://github.com/python-trio/trio/issues/68>`__ for
  details.

* :class:`trio.Queue`\'s ``join`` and ``task_done`` methods are
  deprecated without replacement (`#321
  <https://github.com/python-trio/trio/issues/321>`__)

* Trio 0.1.0 provided a set of built-in mechanisms for waiting for and
  tracking the result of individual tasks. We haven't yet found any
  cases where using this actually led to simpler code, though, and
  this feature is blocking useful improvements, so the following are
  being deprecated without replacement:

  * ``nursery.zombies``
  * ``nursery.monitor``
  * ``nursery.reap``
  * ``nursery.reap_and_unwrap``
  * ``task.result``
  * ``task.add_monitor``
  * ``task.discard_monitor``
  * ``task.wait``

  This also lets us move a number of lower-level features out of the
  main :mod:`trio` namespace and into :mod:`trio.hazmat`:

  * ``trio.Task`` → :class:`trio.hazmat.Task`
  * ``trio.current_task`` → :func:`trio.hazmat.current_task`
  * ``trio.Result`` → :class:`trio.hazmat.Result`
  * ``trio.Value`` → :class:`trio.hazmat.Value`
  * ``trio.Error`` → :class:`trio.hazmat.Error`
  * ``trio.UnboundedQueue`` → :class:`trio.hazmat.UnboundedQueue`

  In addition, several introspection attributes are being renamed:

  * ``nursery.children`` → ``nursery.child_tasks``
  * ``task.parent_task`` → use ``task.parent_nursery.parent_task`` instead

  See `#136 <https://github.com/python-trio/trio/issues/136>`__ for
  more details.

* To consolidate introspection functionality in :mod:`trio.hazmat`,
  the following functions are moving:

  * ``trio.current_clock`` → :func:`trio.hazmat.current_clock`
  * ``trio.current_statistics`` → :func:`trio.hazmat.current_statistics`

  See `#317 <https://github.com/python-trio/trio/issues/317>`__ for
  more details.

* It was decided that 0.1.0's "yield point" terminology was confusing;
  we now use :ref:`"checkpoint" <checkpoints>` instead. As part of
  this, the following functions in :mod:`trio.hazmat` are changing
  names:

  * ``yield_briefly`` → :func:`~trio.hazmat.checkpoint`
  * ``yield_briefly_no_cancel`` → :func:`~trio.hazmat.cancel_shielded_checkpoint`
  * ``yield_if_cancelled`` → :func:`~trio.hazmat.checkpoint_if_cancelled`
  * ``yield_indefinitely`` → :func:`~trio.hazmat.wait_task_rescheduled`

  In addition, the following functions in :mod:`trio.testing` are
  changing names:

  * ``assert_yields`` → :func:`~trio.testing.assert_checkpoints`
  * ``assert_no_yields`` → :func:`~trio.testing.assert_no_checkpoints`

  See `#157 <https://github.com/python-trio/trio/issues/157>`__ for
  more details.

* ``trio.format_exception`` is deprecated; use
  :func:`traceback.format_exception` instead (`#347
  <https://github.com/python-trio/trio/pull/347>`__).

* ``trio.current_instruments`` is deprecated. For adding or removing
  instrumentation at run-time, see :func:`trio.hazmat.add_instrument`
  and :func:`trio.hazmat.remove_instrument` (`#257
  <https://github.com/python-trio/trio/issues/257>`__)

Unfortunately, a limitation in PyPy3 5.8 breaks our deprecation
handling for some renames. (Attempting to use the old names will give
an unhelpful error instead of a helpful warning.) This does not affect
CPython, or PyPy3 5.9+.


Other changes
~~~~~~~~~~~~~

* :func:`run_sync_in_worker_thread` now has a :ref:`robust mechanism
  for applying capacity limits to the number of concurrent threads
  <worker-thread-limiting>` (`#10
  <https://github.com/python-trio/trio/issues/170>`__, `#57
  <https://github.com/python-trio/trio/issues/57>`__, `#156
  <https://github.com/python-trio/trio/issues/156>`__)

* New support for tests to cleanly hook hostname lookup and socket
  operations: see :ref:`virtual-network-hooks`. In addition,
  ``trio.socket.SocketType`` is now an empty abstract base class, with
  the actual socket class made private. This shouldn't effect anyone,
  since the only thing you could directly use it for in the first
  place was ``isinstance`` checks, and those still work (`#170
  <https://github.com/python-trio/trio/issues/170>`__)

* New class :class:`StrictFIFOLock`

* New exception :exc:`ResourceBusyError`

* The :class:`trio.hazmat.ParkingLot` class (which is used to
  implement many of Trio's synchronization primitives) was rewritten
  to be simpler and faster (`#272
  <https://github.com/python-trio/trio/issues/272>`__, `#287
  <https://github.com/python-trio/trio/issues/287>`__)

* It's generally true that if you're using Trio you have to use Trio
  functions, if you're using asyncio you have to use asyncio
  functions, and so forth. (See the discussion of the "async sandwich"
  in the Trio tutorial for more details.) So for example, this isn't
  going to work::

      async def main():
          # asyncio here
          await asyncio.sleep(1)

      # trio here
      trio.run(main)

  Trio now reliably detects if you accidentally do something like
  this, and gives a helpful error message.

* Trio now also has special error messages for several other common
  errors, like doing ``trio.run(some_func())`` (should be
  ``trio.run(some_func)``).

* :mod:`trio.socket` now handles non-ascii domain names using the
  modern IDNA 2008 standard instead of the obsolete IDNA 2003 standard
  (`#11 <https://github.com/python-trio/trio/issues/11>`__)

* When an :class:`~trio.abc.Instrument` raises an unexpected error, we
  now route it through the :mod:`logging` module instead of printing
  it directly to stderr. Normally this produces exactly the same
  effect, but this way it's more configurable. (`#306
  <https://github.com/python-trio/trio/issues/306>`__)

* Fixed a minor race condition in IOCP thread shutdown on Windows
  (`#81 <https://github.com/python-trio/trio/issues/81>`__)

* Control-C handling on Windows now uses :func:`signal.set_wakeup_fd`
  and should be more reliable (`#42
  <https://github.com/python-trio/trio/issues/42>`__)

* :func:`trio.run` takes a new keyword argument
  ``restrict_keyboard_interrupt_to_checkpoints``

* New attributes allow more detailed introspection of the task tree:
  ``nursery.child_tasks``, ``Task.child_nurseries``,
  ``nursery.parent_task``, ``Task.parent_nursery``

* :func:`trio.testing.wait_all_tasks_blocked` now takes a
  ``tiebreaker=`` argument. The main use is to allow
  :class:`~trio.testing.MockClock`\'s auto-jump functionality to avoid
  interfering with direct use of
  :func:`~trio.testing.wait_all_tasks_blocked` in the same test.

* :meth:`MultiError.catch` now correctly preserves ``__context__``,
  despite Python's best attempts to stop us (`#165
  <https://github.com/python-trio/trio/issues/165>`__)

* It is now possible to take weakrefs to :class:`Lock` and many other
  classes (`#331 <https://github.com/python-trio/trio/issues/331>`__)

* Fix ``sock.accept()`` for IPv6 sockets (`#164
  <https://github.com/python-trio/trio/issues/164>`__)

* PyCharm (and hopefully other IDEs) can now offer better completions
  for the :mod:`trio` and :mod:`trio.hazmat` modules (`#314
  <https://github.com/python-trio/trio/issues/314>`__)

* Trio now uses `yapf <https://github.com/google/yapf>`__ to
  standardize formatting across the source tree, so we never have to
  think about whitespace again.

* Many documentation improvements


Trio 0.1.0 (2017-03-10)
-----------------------

* Initial release.
