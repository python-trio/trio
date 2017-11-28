Release history
===============

.. currentmodule:: trio

.. towncrier release notes start

Trio 0.2.0 (coming soon)
------------------------

Trio 0.2.0 contains changes from 14 contributors, and brings major new
features and bug fixes, as well as a number of deprecations and a very
small number of backwards incompatible changes. We anticipate that
these should be easy to adapt to, but make sure to read about them
below, and if you're using Trio then remember to `read and subscribe
to issue #1 <https://github.com/python-trio/trio/issues/1>`__.


Highlights
~~~~~~~~~~

* Added a comprehensive API for async file I/O: see
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
  <abstract-stream-api>`, along with helpers for :ref:`creating fake
  streams for testing <virtual-streams>` and :ref:`checking that your
  custom stream implementations follow the abstract contract
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
  applying encryption to arbitrary :class:`Stream`\s, which allows for
  interesting applications like `TLS-over-TLS
  <https://daniel.haxx.se/blog/2016/11/26/https-proxy-with-curl/>`__.
  See: :func:`trio.open_ssl_over_tcp_stream`,
  :func:`trio.serve_ssl_over_tcp`,
  :func:`trio.open_ssl_over_tcp_listeners`, and :mod:`trio.ssl`.

  Interesting fact: the test suite for :mod:`trio.ssl` has already
  found bugs in CPython's ssl module, PyPy's ssl module, PyOpenSSL,
  and OpenSSL. (Trio doesn't use PyOpenSSL.) Trio's test suite is very
  thorough.

* You know thread-local storage? Well, Trio now has an equivalent:
  :ref:`task-local storage <task-local-storage>`. There's also the
  related, but more obscure, run-local storage; see
  :class:`~trio.hazmat.RunLocal`. (`#2
  <https://github.com/python-trio/trio/pull/2>`__)


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

Breaking changes (all very minor):

* When a socket ``sendall`` call was cancelled, it used to attach some
  metadata to the exception reporting how much data was actually sent.
  It no longer does this, because in common configurations like an
  :class:`~trio.ssl.SSLStream` wrapped around a
  :class:`~trio.SocketStream` it becomes ambiguous which "level" the
  partial send metadata applies to, leading to confusion and bugs.
  There is no longer any way to tell how much data was sent after a
  ``sendall`` is cancelled.

* The :func:`trio.socket.getprotobyname` function is now async, like
  it should have been all along. I doubt anyone will ever use it, but
  that's no reason not to get the details right.

* The :mod:`trio.socket` functions ``getservbyport``,
  ``getservbyname``, and ``getfqdn`` have been removed, because they
  were obscure, buggy, and obsolete. Use
  :func:`~trio.socket.getaddrinfo` instead.

Upcoming breaking changes without warnings (i.e., stuff that in 0.2.0
will work, but won't work in 0.3.0):

* In the next release, the ``bind`` method on Trio socket objects will
  become async (XX). Unfortunately, there's no good way to provide a
  warning here. We recommend switching to the new highlevel networking
  APIs like :func:`serve_tcp`, which will insulate you from this change.

Upcoming breaking changes with warnings (i.e., stuff that in 0.2.0
*will* work but complain loudly, and won't work in 0.3.0):

* For consistency with the new ``start`` method, the nursery ``spawn``
  method is being renamed to ``start_soon`` (`#284
  <https://github.com/python-trio/trio/issues/284>`__)

* ``trio.socket.sendall`` is deprecated; use ``SocketStream.send_all``
  instead (`#291 <https://github.com/python-trio/trio/issues/291>`__)

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
  * ``trio.current_statistics`` → func:`trio.hazmat.current_statistics`

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

* ``trio.format_traceback`` is deprecated; use
  :func:`traceback.format_traceback` instead (`#347
  <https://github.com/python-trio/trio/pull/347>`__).

* ``run_in_worker_thread`` → ``run_sync_in_worker_thread`` (`#68 <https://github.com/python-trio/trio/issues/68>`__

``current_call_soon_thread_and_signal_safe`` → :class:`trio.hazmat.TrioToken`
``run_in_trio_thread``, ``await_in_trio_thread`` → :class:`trio.BlockingTrioPortal`

deprecated big chunks of nursery and Task API

queue join and task_done are deprecated


Backwards-incompatible changes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~




Exceptions from instrumentation are now routed through the logging
module (gh-306)

testing helpers


ParkingLot is rewritten to be simpler and faster (gh-272, gh-287)

trio.socket no longer overrides socket options

controlled way to override hostname resolution and socket behavior in
tests (gh-170)

using yapf now

capacity limitation for threads (gh-10, gh-57, gh-156)

Reliably detect when someone tries to use an incompatible flavor of
async library (e.g. asyncio or curio) and give a helpful error message

IDNA 2008 support in trio.socket (gh-11)

rename yield point to checkpoint

fix minor face condition in IOCP thread shutdown (gh-81)

switch to using set_wakeup_fd to detect control-C on Windows (gh-42)

lots of doc improvements

restrict_keyboard_interrupt_to_checkpoints

``tiebreaker=`` argument to
:func:`trio.testing.wait_all_tasks_blocked`

:class:`StrictFIFOLock`

:class:`ResourceBusyError`

:meth:`MultiError.catch` now correctly preserves ``__context__``,
despite Python's best attempts to stop us. (gh-165)

:class:`Lock` and many other classes now support weakrefs (gh-331)

nursery.child_tasks, nursery.parent_task, task.child_nurseries,
task.parent_nursery

Fix ``sock.accept()`` for IPv6 sockets (https://github.com/python-trio/trio/issues/164)

PyCharm (and hopefully other IDEs) offer better completions for
the :mod:`trio` and :mod:`trio.hazmat` modules
https://github.com/python-trio/trio/issues/314


``trio.socket.SocketType`` is now an empty abstract base class, with
the actual socket class made private. This shouldn't effect anyone,
since the only thing you could directly use it for in the first place
was ``isinstance`` checks, and those still work
(https://github.com/python-trio/trio/issues/170)

* The following classes and functions have moved from :mod:`trio` to
  :mod:`trio.hazmat`:

  - :class:`~trio.hazmat.Task`
  - :class:`~trio.hazmat.UnboundedQueue`
  - :class:`~trio.hazmat.Result`
  - :class:`~trio.hazmat.Error`
  - :class:`~trio.hazmat.Value`
  - :func:`~trio.hazmat.current_task`
  - :func:`~trio.hazmat.current_clock`
  - :func:`~trio.hazmat.current_statistics`

deprecate most of the task and nursery APIs

make our exports visible to PyCharm (314)

Renames from https://github.com/python-trio/trio/issues/157

Note that pypy needs 5.9+ to support deprecations properly



Features
~~~~~~~~

* New argument to :func:`trio.run`:
  ``restrict_keyboard_interrupt_to_checkpoints``.



Trio 0.1.0 (2017-03-10)
-----------------------

* Initial release.
