Release history
===============

.. currentmodule:: trio

.. towncrier release notes start

Trio 0.2.0 (coming soon)
------------------------

[this has notes up to 3613ca6df]

Highlights
~~~~~~~~~~

Async I/O for files and filesystem operations: :func:`trio.open_file`,
:func:`trio.Path`

Complete support for TLS over arbitrary transports, including
STARTTLS, renegotiation during full-duplex usage, and `TLS-over-TLS
<https://daniel.haxx.se/blog/2016/11/26/https-proxy-with-curl/>`__:
:func:`trio.open_ssl_over_tcp_stream`,
:func:`trio.serve_ssl_over_tcp`,
:func:`trio.open_ssl_over_tcp_listeners`, and :mod:`trio.ssl`

``nursery.start`` (and rename ``spawn`` to ``start_soon``)

High-level networking interface

testing helpers

Happy eyeballs

Task- and run-local storage (gh-2)


ParkingLot is rewritten to be simpler and faster (gh-272, gh-287)

trio.socket no longer overrides socket options

breaking: getprotobyname is now async
getservbyport, getservbyname, getfqdn removed (they're buggy and obsolete)

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

sendall no longer has partial result notification – this could be
misleading with stream wrappers like :class:`~trio.ssl.SSLStream`

:class:`ResourceBusyError`

:meth:`MultiError.catch` now correctly preserves ``__context__``,
despite Python's bets attempts to stop us. (gh-165)

nursery.child_tasks, nursery.parent_task, task.child_nurseries,
task.parent_nursery

Fix ``sock.accept()`` for IPv6 sockets (https://github.com/python-trio/trio/issues/164)


* ``trio.socket.SocketType`` will no longer be exposed publically in
  0.3.0. Since it had no public constructor, the only thing you could
  do with it was ``isinstance(obj, SocketType)``. Instead, use
  :func:`trio.socket.is_trio_socket`. (https://github.com/python-trio/trio/issues/170)

* The following classes and functions have moved from :mod:`trio` to
  :mod:`trio.hazmat`:

  - :class:`~trio.hazmat.Task`
  - :class:`~trio.hazmat.UnboundedQueue`
  - :class:`~trio.hazmat.Result`
  - :class:`~trio.hazmat.Error`
  - :class:`~trio.hazmat.Value`
  - :func:`~trio.hazmat.current_task`

deprecate most of the task and nursery APIs

make our exports visible to PyCharm (314)

Renames from https://github.com/python-trio/trio/issues/157

Note that pypy needs 5.9+ to support deprecations properly

Breaking changes and deprecations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Trio is a young project; link to issue #1

Breaking changes:

  It turns out

Upcoming breaking changes without warnings (i.e., stuff that in 0.2.0
will work, but won't work in 0.3.0):

* In the next release, the ``bind`` method on Trio socket objects will
  become async (XX). Unfortunately, there's no good way to warn about
  this. If you switch to the new highlevel networking APIs then
  then they'll insulate you from this change.

Upcoming breaking changes with warnings (i.e., stuff that in 0.2.0
will work but complain loudly, and won't work in 0.3.0):

*

``sendall``

``run_in_worker_thread`` → ``run_sync_in_worker_thread``
``nursery.spawn`` → ``nursery.start_soon``

deprecated big chunks of nursery and Task API


Features
~~~~~~~~

* New argument to :func:`trio.run`:
  ``restrict_keyboard_interrupt_to_checkpoints``.



Trio 0.1.0 (2017-03-10)
-----------------------

* Initial release.
