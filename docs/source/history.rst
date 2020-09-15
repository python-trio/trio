Release history
===============

.. currentmodule:: trio

.. towncrier release notes start

Trio 0.17.0 (2020-09-15)
------------------------

Headline features
~~~~~~~~~~~~~~~~~

- Trio now supports automatic :ref:`async generator finalization
  <async-generators>`, so more async generators will work even if you
  don't wrap them in ``async with async_generator.aclosing():``
  blocks. Please see the documentation for important caveats; in
  particular, yielding within a nursery or cancel scope remains
  unsupported. (`#265 <https://github.com/python-trio/trio/issues/265>`__)


Features
~~~~~~~~

- `trio.open_tcp_stream` has a new ``local_address=`` keyword argument
  that can be used on machines with multiple IP addresses to control
  which IP is used for the outgoing connection. (`#275 <https://github.com/python-trio/trio/issues/275>`__)
- If you pass a raw IP address into ``sendto``, it no longer spends any
  time trying to resolve the hostname. If you're using UDP, this should
  substantially reduce your per-packet overhead. (`#1595 <https://github.com/python-trio/trio/issues/1595>`__)
- `trio.lowlevel.checkpoint` is now much faster. (`#1613 <https://github.com/python-trio/trio/issues/1613>`__)
- We switched to a new, lower-overhead data structure to track upcoming
  timeouts, which should make your programs faster. (`#1629 <https://github.com/python-trio/trio/issues/1629>`__)


Bugfixes
~~~~~~~~

- On macOS and BSDs, explicitly close our wakeup socketpair when we're
  done with it. (`#1621 <https://github.com/python-trio/trio/issues/1621>`__)
- Trio can now be imported when `sys.excepthook` is a `functools.partial` instance, which might occur in a
  ``pytest-qt`` test function. (`#1630 <https://github.com/python-trio/trio/issues/1630>`__)
- The thread cache didn't release its reference to the previous job. (`#1638 <https://github.com/python-trio/trio/issues/1638>`__)
- On Windows, Trio now works around the buggy behavior of certain
  Layered Service Providers (system components that can intercept
  network activity) that are built on top of a commercially available
  library called Komodia Redirector. This benefits users of products
  such as Astrill VPN and Qustodio parental controls. Previously, Trio
  would crash on startup when run on a system where such a product was
  installed. (`#1659 <https://github.com/python-trio/trio/issues/1659>`__)


Deprecations and removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- Remove ``wait_socket_*``, ``notify_socket_closing``, ``notify_fd_closing``, ``run_sync_in_worker_thread`` and ``current_default_worker_thread_limiter``. They were deprecated in 0.12.0. (`#1596 <https://github.com/python-trio/trio/issues/1596>`__)


Miscellaneous internal changes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- When using :ref:`instruments <instrumentation>`, you now only "pay for what you use":
  if there are no instruments installed that override a particular hook such as
  :meth:`~trio.abc.Instrument.before_task_step`, then Trio doesn't waste any effort
  on checking its instruments when the event corresponding to that hook occurs.
  Previously, installing any instrument would incur all the instrumentation overhead,
  even for hooks no one was interested in. (`#1340 <https://github.com/python-trio/trio/issues/1340>`__)


Trio 0.16.0 (2020-06-10)
------------------------

Headline features
~~~~~~~~~~~~~~~~~

- If you want to use Trio, but are stuck with some other event loop like
  Qt or PyGame, then good news: now you can have both. For details, see:
  :ref:`guest-mode`. (`#399 <https://github.com/python-trio/trio/issues/399>`__)


Features
~~~~~~~~

- To speed up `trio.to_thread.run_sync`, Trio now caches and re-uses
  worker threads.

  And in case you have some exotic use case where you need to spawn
  threads manually, but want to take advantage of Trio's cache, you can
  do that using the new `trio.lowlevel.start_thread_soon`. (`#6 <https://github.com/python-trio/trio/issues/6>`__)
- Tasks spawned with `nursery.start() <trio.Nursery.start>` aren't treated as
  direct children of their nursery until they call ``task_status.started()``.
  This is visible through the task tree introspection attributes such as
  `Task.parent_nursery <trio.lowlevel.Task.parent_nursery>`. Sometimes, though,
  you want to know where the task is going to wind up, even if it hasn't finished
  initializing yet. To support this, we added a new attribute
  `Task.eventual_parent_nursery <trio.lowlevel.Task.eventual_parent_nursery>`.
  For a task spawned with :meth:`~trio.Nursery.start` that hasn't yet called
  ``started()``, this is the nursery that the task was nominally started in,
  where it will be running once it finishes starting up. In all other cases,
  it is ``None``. (`#1558 <https://github.com/python-trio/trio/issues/1558>`__)


Bugfixes
~~~~~~~~

- Added a helpful error message if an async function is passed to `trio.to_thread.run_sync`. (`#1573 <https://github.com/python-trio/trio/issues/1573>`__)


Deprecations and removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- Remove ``BlockingTrioPortal``: it was deprecated in 0.12.0. (`#1574 <https://github.com/python-trio/trio/issues/1574>`__)
- The ``tiebreaker`` argument to `trio.testing.wait_all_tasks_blocked`
  has been deprecated. This is a highly obscure feature that was
  probably never used by anyone except `trio.testing.MockClock`, and
  `~trio.testing.MockClock` doesn't need it anymore. (`#1587 <https://github.com/python-trio/trio/issues/1587>`__)
- Remove the deprecated ``trio.ssl`` and ``trio.subprocess`` modules. (`#1594 <https://github.com/python-trio/trio/issues/1594>`__)


Miscellaneous internal changes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- We refactored `trio.testing.MockClock` so that it no longer needs to
  run an internal task to manage autojumping. This should be mostly
  invisible to users, but there is one semantic change: the interaction
  between `trio.testing.wait_all_tasks_blocked` and the autojump clock
  was fixed. Now, the autojump will always wait until after all
  `~trio.testing.wait_all_tasks_blocked` calls have finished before
  firing, instead of it depending on which threshold values you passed. (`#1587 <https://github.com/python-trio/trio/issues/1587>`__)


Trio 0.15.1 (2020-05-22)
------------------------

Bugfixes
~~~~~~~~

- Fix documentation build. (This must be a new release tag to get readthedocs
  "stable" to include the changes from 0.15.0.)

- Added a helpful error message if an async function is passed to `trio.from_thread.run_sync` or a sync function to `trio.from_thread.run`. (`#1244 <https://github.com/python-trio/trio/issues/1244>`__)


Trio 0.15.0 (2020-05-19)
------------------------

Features
~~~~~~~~

- Previously, when `trio.run_process` was cancelled, it always killed
  the subprocess immediately. Now, on Unix, it first gives the process a
  chance to clean up by sending ``SIGTERM``, and only escalates to
  ``SIGKILL`` if the process is still running after 5 seconds. But if
  you prefer the old behavior, or want to adjust the timeout, then don't
  worry: you can now pass a custom ``deliver_cancel=`` argument to
  define your own process killing policy. (`#1104 <https://github.com/python-trio/trio/issues/1104>`__)
- It turns out that creating a subprocess can block the parent process
  for a surprisingly long time. So `trio.open_process` now uses a worker
  thread to avoid blocking the event loop. (`#1109 <https://github.com/python-trio/trio/issues/1109>`__)
- We've added FreeBSD to the list of platforms we support and test on. (`#1118 <https://github.com/python-trio/trio/issues/1118>`__)
- On Linux kernels v5.3 or newer, `trio.Process.wait` now uses `the
  pidfd API <https://lwn.net/Articles/794707/>`__ to track child
  processes. This shouldn't have any user-visible change, but it makes
  working with subprocesses faster and use less memory. (`#1241 <https://github.com/python-trio/trio/issues/1241>`__)
- The `trio.Process.returncode` attribute is now automatically updated
  as needed, instead of only when you call `~trio.Process.poll` or
  `~trio.Process.wait`. Also, ``repr(process_object)`` now always
  contains up-to-date information about the process status. (`#1315 <https://github.com/python-trio/trio/issues/1315>`__)


Bugfixes
~~~~~~~~

- On Ubuntu systems, the system Python includes a custom
  unhandled-exception hook to perform `crash reporting
  <https://wiki.ubuntu.com/Apport>`__. Unfortunately, Trio wants to use
  the same hook to print nice `MultiError` tracebacks, causing a
  conflict. Previously, Trio would detect the conflict, print a warning,
  and you just wouldn't get nice `MultiError` tracebacks. Now, Trio has
  gotten clever enough to integrate its hook with Ubuntu's, so the two
  systems should Just Work together. (`#1065 <https://github.com/python-trio/trio/issues/1065>`__)
- Fixed an over-strict test that caused failures on Alpine Linux.
  Started testing against Alpine in CI. (`#1499 <https://github.com/python-trio/trio/issues/1499>`__)
- Calling `open_signal_receiver` with no arguments used to succeed without listening for any signals. This was confusing, so now it raises TypeError instead. (`#1526 <https://github.com/python-trio/trio/issues/1526>`__)


Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- Remove support for Python 3.5. (`#75 <https://github.com/python-trio/trio/issues/75>`__)
- It turns out that everyone got confused by the name ``trio.hazmat``.
  So that name has been deprecated, and the new name is
  :mod:`trio.lowlevel`. (`#476 <https://github.com/python-trio/trio/issues/476>`__)
- Most of the public classes that Trio exports – like `trio.Lock`,
  `trio.SocketStream`, and so on – weren't designed with subclassing in
  mind. And we've noticed that some users were trying to subclass them
  anyway, and ending up with fragile code that we're likely to
  accidentally break in the future, or else be stuck unable to make
  changes for fear of breaking subclasses.

  There are also some classes that were explicitly designed to be
  subclassed, like the ones in ``trio.abc``. Subclassing these is still
  supported. However, for all other classes, attempts to subclass will
  now raise a deprecation warning, and in the future will raise an
  error.

  If this causes problems for you, feel free to drop by our `chat room
  <https://gitter.im/python-trio/general>`__ or file a bug, to discuss
  alternatives or make a case for why some particular class should be
  designed to support subclassing. (`#1044 <https://github.com/python-trio/trio/issues/1044>`__)
- If you want to create a `trio.Process` object, you now have to call
  `trio.open_process`; calling ``trio.Process()`` directly was
  deprecated in v0.12.0 and has now been removed. (`#1109 <https://github.com/python-trio/trio/issues/1109>`__)
- Remove ``clear`` method on `trio.Event`: it was deprecated in 0.12.0. (`#1498 <https://github.com/python-trio/trio/issues/1498>`__)


Trio 0.14.0 (2020-04-27)
------------------------

Features
~~~~~~~~

- If you're using Trio's low-level interfaces like
  `trio.hazmat.wait_readable <trio.lowlevel.wait_readable>` or similar, and then you close a socket or
  file descriptor, you're supposed to call `trio.hazmat.notify_closing
  <trio.lowlevel.notify_closing>`
  first so Trio can clean up properly. But what if you forget? In the
  past, Trio would tend to either deadlock or explode spectacularly.
  Now, it's much more robust to this situation, and should generally
  survive. (But note that "survive" is not the same as "give you the
  results you were expecting", so you should still call
  `~trio.lowlevel.notify_closing` when appropriate. This is about harm
  reduction and making it easier to debug this kind of mistake, not
  something you should rely on.)

  If you're using higher-level interfaces outside of the `trio.hazmat <trio.lowlevel>`
  module, then you don't need to worry about any of this; those
  intefaces already take care of calling `~trio.lowlevel.notify_closing`
  for you. (`#1272 <https://github.com/python-trio/trio/issues/1272>`__)


Bugfixes
~~~~~~~~

- A bug related to the following methods has been introduced in version 0.12.0:

  - `trio.Path.iterdir`
  - `trio.Path.glob`
  - `trio.Path.rglob`

  The iteration of the blocking generators produced by pathlib was performed in
  the trio thread. With this fix, the previous behavior is restored: the blocking
  generators are converted into lists in a thread dedicated to blocking IO calls. (`#1308 <https://github.com/python-trio/trio/issues/1308>`__)


Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- Deprecate Python 3.5 (`#1408 <https://github.com/python-trio/trio/pull/1408>`__)
- Remove ``trio.open_cancel_scope`` which was deprecated in 0.11.0. (`#1458 <https://github.com/python-trio/trio/issues/1458>`__)


Trio 0.13.0 (2019-11-02)
------------------------

Features
~~~~~~~~

- On Windows, the `IOCP subsystem
  <https://docs.microsoft.com/en-us/windows/win32/fileio/i-o-completion-ports>`__
  is generally the best way to implement async I/O operations – but it's
  historically been weak at providing ``select``\-style readiness
  notifications, like `trio.hazmat.wait_readable <trio.lowlevel.wait_readable>` and
  `~trio.lowlevel.wait_writable`. We aren't willing to give those up, so
  previously Trio's Windows backend used a hybrid of ``select`` + IOCP.
  This was complex, slow, and had `limited scalability
  <https://github.com/python-trio/trio/issues/3>`__.

  Fortunately, we found a way to implement ``wait_*`` with IOCP, so
  Trio's Windows backend has been completely rewritten, and now uses
  IOCP exclusively. As a user, the only difference you should notice is
  that Trio should now be faster on Windows, and can handle many more
  sockets. This also simplified the code internally, which should allow
  for more improvements in the future.

  However, this is somewhat experimental, so if you use Windows then
  please keep an eye out and let us know if you run into any problems! (`#52 <https://github.com/python-trio/trio/issues/52>`__)
- Use slots for memory channel state and statistics which should make memory channels slightly smaller and faster. (`#1195 <https://github.com/python-trio/trio/issues/1195>`__)


Bugfixes
~~~~~~~~

- OpenSSL has a bug in its handling of TLS 1.3 session tickets that can
  cause deadlocks or data loss in some rare edge cases. These edge cases
  most frequently happen during tests. (Upstream bug reports: `openssl/openssl#7948
  <https://github.com/openssl/openssl/issues/7948>`__, `openssl/openssl#7967
  <https://github.com/openssl/openssl/issues/7967>`__.) `trio.SSLStream`
  now works around this issue, so you don't have to worry about it. (`#819 <https://github.com/python-trio/trio/issues/819>`__)
- Trio now uses `signal.set_wakeup_fd` on all platforms. This is mostly
  an internal refactoring with no user-visible effect, but in theory it
  should fix a few extremely-rare race conditions on Unix that could
  have caused signal delivery to be delayed. (`#109 <https://github.com/python-trio/trio/issues/109>`__)
- Trio no longer crashes when an async function is implemented in C or
  Cython and then passed directly to `trio.run` or
  ``nursery.start_soon``. (`#550 <https://github.com/python-trio/trio/issues/550>`__, `#1191 <https://github.com/python-trio/trio/issues/1191>`__)
- When a Trio task makes improper use of a non-Trio async library, Trio now causes an exception to be raised within the task at the point of the error, rather than abandoning the task and raising an error in its parent. This improves debuggability and resolves the `TrioInternalError` that would sometimes result from the old strategy. (`#552 <https://github.com/python-trio/trio/issues/552>`__)
- In 0.12.0 we deprecated ``trio.run_sync_in_worker_thread`` in favor of
  `trio.to_thread.run_sync`. But, the deprecation message listed the
  wrong name for the replacement. The message now gives the correct name. (`#810 <https://github.com/python-trio/trio/issues/810>`__)
- Fix regression introduced with cancellation changes in 0.12.0, where a
  `trio.CancelScope` which isn't cancelled could catch a propagating
  `trio.Cancelled` exception if shielding were changed while the
  cancellation was propagating. (`#1175 <https://github.com/python-trio/trio/issues/1175>`__)
- Fix a crash that could happen when using ``MockClock`` with autojump
  enabled and a non-zero rate. (`#1190 <https://github.com/python-trio/trio/issues/1190>`__)
- If you nest >1000 cancel scopes within each other, Trio now handles
  that gracefully instead of crashing with a ``RecursionError``. (`#1235 <https://github.com/python-trio/trio/issues/1235>`__)
- Fixed the hash behavior of `trio.Path` to match `pathlib.Path`. Previously `trio.Path`'s hash was inherited from `object` instead of from `pathlib.PurePath`. Thus, hashing two `trio.Path`\'s or a `trio.Path` and a `pathlib.Path` with the same underlying path would yield different results. (`#1259 <https://github.com/python-trio/trio/issues/1259>`__)


Trio 0.12.1 (2019-08-01)
------------------------

Bugfixes
~~~~~~~~

- In v0.12.0, we accidentally moved ``BlockingTrioPortal`` from ``trio``
  to ``trio.hazmat``. It's now been restored to its proper position.
  (It's still deprecated though, and will issue a warning if you use it.) (`#1167 <https://github.com/python-trio/trio/issues/1167>`__)


Trio 0.12.0 (2019-07-31)
------------------------

Features
~~~~~~~~

- If you have a `~trio.abc.ReceiveStream` object, you can now use
  ``async for data in stream: ...`` instead of calling
  `~trio.abc.ReceiveStream.receive_some`. Each iteration gives an
  arbitrary sized chunk of bytes. And the best part is, the loop
  automatically exits when you reach EOF, so you don't have to check for
  it yourself anymore. Relatedly, you no longer need to pick a magic
  buffer size value before calling
  `~trio.abc.ReceiveStream.receive_some`; you can ``await
  stream.receive_some()`` with no arguments, and the stream will
  automatically pick a reasonable size for you. (`#959 <https://github.com/python-trio/trio/issues/959>`__)
- Threading interfaces have been reworked:
  ``run_sync_in_worker_thread`` is now `trio.to_thread.run_sync`, and
  instead of ``BlockingTrioPortal``, use `trio.from_thread.run` and
  `trio.from_thread.run_sync`. What's neat about this is that these
  cooperate, so if you're in a thread created by `to_thread.run_sync`,
  it remembers which Trio created it, and you can call
  ``trio.from_thread.*`` directly without having to pass around a
  ``BlockingTrioPortal`` object everywhere. (`#810 <https://github.com/python-trio/trio/issues/810>`__)
- We cleaned up the distinction between the "abstract channel interface"
  and the "memory channel" concrete implementation.
  `trio.abc.SendChannel` and `trio.abc.ReceiveChannel` have been slimmed
  down, `trio.MemorySendChannel` and `trio.MemoryReceiveChannel` are now
  public types that can be used in type hints, and there's a new
  `trio.abc.Channel` interface for future bidirectional channels. (`#719 <https://github.com/python-trio/trio/issues/719>`__)
- Add :func:`trio.run_process` as a high-level helper for running a process
  and waiting for it to finish, like the standard :func:`subprocess.run` does. (`#822 <https://github.com/python-trio/trio/issues/822>`__)
- On Linux, when wrapping a bare file descriptor in a Trio socket object,
  Trio now auto-detects the correct ``family``, ``type``, and ``protocol``.
  This is useful, for example, when implementing `systemd socket activation
  <http://0pointer.de/blog/projects/socket-activation.html>`__. (`#251 <https://github.com/python-trio/trio/issues/251>`__)
- Trio sockets have a new method `~trio.socket.SocketType.is_readable` that allows
  you to check whether a socket is readable. This is useful for HTTP/1.1 clients. (`#760 <https://github.com/python-trio/trio/issues/760>`__)
- We no longer use runtime code generation to dispatch core functions
  like `current_time`. Static analysis tools like mypy and pylint should
  now be able to recognize and analyze all of Trio's top-level functions
  (though some class attributes are still dynamic... we're working on it). (`#805 <https://github.com/python-trio/trio/issues/805>`__)
- Add `trio.hazmat.FdStream <trio.lowlevel.FdStream>` for wrapping a Unix file descriptor as a `~trio.abc.Stream`. (`#829 <https://github.com/python-trio/trio/issues/829>`__)
- Trio now gives a reasonable traceback and error message in most cases
  when its invariants surrounding cancel scope nesting have been
  violated. (One common source of such violations is an async generator
  that yields within a cancel scope.) The previous behavior was an
  inscrutable chain of TrioInternalErrors. (`#882 <https://github.com/python-trio/trio/issues/882>`__)
- MultiError now defines its ``exceptions`` attribute in ``__init__()``
  to better support linters and code autocompletion. (`#1066 <https://github.com/python-trio/trio/issues/1066>`__)
- Use ``__slots__`` in more places internally, which should make Trio slightly faster. (`#984 <https://github.com/python-trio/trio/issues/984>`__)


Bugfixes
~~~~~~~~

- Destructor methods (``__del__``) are now protected against ``KeyboardInterrupt``. (`#676 <https://github.com/python-trio/trio/issues/676>`__)
- The :class:`trio.Path` methods :meth:`~trio.Path.glob` and
  :meth:`~trio.Path.rglob` now return iterables of :class:`trio.Path`
  (not :class:`pathlib.Path`). (`#917 <https://github.com/python-trio/trio/issues/917>`__)
- Inspecting the :attr:`~trio.CancelScope.cancel_called` attribute of a
  not-yet-exited cancel scope whose deadline is in the past now always
  returns ``True``, like you might expect. (Previously it would return
  ``False`` for not-yet-entered cancel scopes, and for active cancel
  scopes until the first checkpoint after their deadline expiry.) (`#958 <https://github.com/python-trio/trio/issues/958>`__)
- The :class:`trio.Path` classmethods, :meth:`~trio.Path.home` and
  :meth:`~trio.Path.cwd`, are now async functions.  Previously, a bug
  in the forwarding logic meant :meth:`~trio.Path.cwd` was synchronous
  and :meth:`~trio.Path.home` didn't work at all. (`#960 <https://github.com/python-trio/trio/issues/960>`__)
- An exception encapsulated within a :class:`MultiError` doesn't need to be
  hashable anymore.

  .. note::

     This is only supported if you are running python >= 3.6.4. You can
     refer to `this github PR <https://github.com/python/cpython/pull/4014>`_
     for details. (`#1005 <https://github.com/python-trio/trio/issues/1005>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- To help any user reading through Trio's function implementations, start using public names (not _core) whenever possible. (`#1017 <https://github.com/python-trio/trio/issues/1017>`__)


Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- The ``clear`` method on `trio.Event` has been deprecated. (`#637 <https://github.com/python-trio/trio/issues/637>`__)
- ``BlockingTrioPortal`` has been deprecated in favor of the new
  `trio.from_thread`.  (`#810
  <https://github.com/python-trio/trio/issues/810>`__)
- ``run_sync_in_worker_thread`` is deprecated in favor of
  `trio.to_thread.run_sync`.  (`#810
  <https://github.com/python-trio/trio/issues/810>`__)
- ``current_default_worker_thread_limiter`` is deprecated in favor of
  `trio.to_thread.current_default_thread_limiter`. (`#810
  <https://github.com/python-trio/trio/issues/810>`__)
- Give up on trying to have different low-level waiting APIs on Unix and
  Windows. All platforms now have `trio.hazmat.wait_readable <trio.lowlevel.wait_readable>`,
  `trio.hazmat.wait_writable <trio.lowlevel.wait_writable>`, and
  `trio.hazmat.notify_closing <trio.lowlevel.notify_closing>`. The old
  platform-specific synonyms ``wait_socket_*``,
  ``notify_socket_closing``, and ``notify_fd_closing`` have been
  deprecated. (`#878 <https://github.com/python-trio/trio/issues/878>`__)
- It turns out that it's better to treat subprocess spawning as an async
  operation. Therefore, direct construction of `Process` objects has
  been deprecated. Use `trio.open_process` instead. (`#1109 <https://github.com/python-trio/trio/issues/1109>`__)


Miscellaneous internal changes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- The plumbing of Trio's cancellation system has been substantially overhauled
  to improve performance and ease future planned improvements. Notably, there is
  no longer any internal concept of a "cancel stack", and checkpoints now take
  constant time regardless of the cancel scope nesting depth. (`#58 <https://github.com/python-trio/trio/issues/58>`__)
- We've slightly relaxed our definition of which Trio operations act as
  :ref:`checkpoints <checkpoint-rule>`. A Trio async function that exits by
  throwing an exception is no longer guaranteed to execute a checkpoint;
  it might or might not. The rules are unchanged for async functions that
  don't exit with an exception, async iterators, and async context managers.
  :func:`trio.testing.assert_checkpoints` has been updated to reflect the
  new behavior: if its ``with`` block exits with an exception, no assertion
  is made. (`#474 <https://github.com/python-trio/trio/issues/474>`__)
- Calling ``str`` on a :exc:`trio.Cancelled` exception object returns "Cancelled" instead of an empty string. (`#674 <https://github.com/python-trio/trio/issues/674>`__)
- Change the default timeout in :func:`trio.open_tcp_stream` to 0.250 seconds, for consistency with RFC 8305. (`#762 <https://github.com/python-trio/trio/issues/762>`__)
- On win32 we no longer set SO_EXCLUSIVEADDRUSE when binding a socket in :exc:`trio.open_tcp_listeners`. (`#928 <https://github.com/python-trio/trio/issues/928>`__)
- Any attempt to inherit from `CancelScope` or `Nursery` now raises
  `TypeError`.  (Trio has never been able to safely support subclassing
  here; this change just makes it more obvious.)
  Also exposed as public classes for type-checking, etc. (`#1021 <https://github.com/python-trio/trio/issues/1021>`__)


Trio 0.11.0 (2019-02-09)
------------------------

Features
~~~~~~~~

- Add support for "unbound cancel scopes": you can now construct a
  :class:`trio.CancelScope` without entering its context, e.g., so you
  can pass it to another task which will use it to wrap some work that
  you want to be able to cancel from afar. (`#607 <https://github.com/python-trio/trio/issues/607>`__)
- The test suite now passes with openssl v1.1.1. Unfortunately this
  required temporarily disabling TLS v1.3 during tests; see openssl bugs
  `#7948 <https://github.com/openssl/openssl/issues/7948>`__ and `#7967
  <https://github.com/openssl/openssl/issues/7967>`__. We believe TLS
  v1.3 should work in most real use cases, but will be monitoring the
  situation. (`#817 <https://github.com/python-trio/trio/issues/817>`__)
- Add :attr:`trio.Process.stdio`, which is a :class:`~trio.StapledStream` of
  :attr:`~trio.Process.stdin` and :attr:`~trio.Process.stdout` if both of those
  are available, and ``None`` otherwise. This is intended to make it more
  ergonomic to speak a back-and-forth protocol with a subprocess. (`#862 <https://github.com/python-trio/trio/issues/862>`__)
- :class:`trio.Process` on POSIX systems no longer accepts the error-prone
  combination of ``shell=False`` with a ``command`` that's a single string,
  or ``shell=True`` with a ``command`` that's a sequence of strings.
  These forms are accepted by the underlying :class:`subprocess.Popen`
  constructor but don't do what most users expect. Also, added an explanation
  of :ref:`quoting <subprocess-quoting>` to the documentation. (`#863 <https://github.com/python-trio/trio/issues/863>`__)
- Added an internal mechanism for pytest-trio's
  `Hypothesis <https://hypothesis.readthedocs.io>`__ integration
  to make the task scheduler reproducible and avoid flaky tests. (`#890 <https://github.com/python-trio/trio/issues/890>`__)
- :class:`~trio.abc.SendChannel`, :class:`~trio.abc.ReceiveChannel`, :class:`~trio.abc.Listener`,
  and :func:`~trio.open_memory_channel` can now be referenced using a generic type parameter
  (the type of object sent over the channel or produced by the listener) using PEP 484 syntax:
  ``trio.abc.SendChannel[bytes]``, ``trio.abc.Listener[trio.SocketStream]``,
  ``trio.open_memory_channel[MyMessage](5)``, etc. The added type information does not change
  the runtime semantics, but permits better integration with external static type checkers. (`#908 <https://github.com/python-trio/trio/issues/908>`__)


Bugfixes
~~~~~~~~

- Fixed several bugs in the new Unix subprocess pipe support, where
  (a) operations on a closed pipe could accidentally affect another
  unrelated pipe due to internal file-descriptor reuse, (b) in very rare
  circumstances, two tasks calling ``send_all`` on the same pipe at the
  same time could end up with intermingled data instead of a
  :exc:`BusyResourceError`. (`#661 <https://github.com/python-trio/trio/issues/661>`__)
- Stop :func:`trio.open_tcp_listeners` from crashing on systems that have
  disabled IPv6. (`#853 <https://github.com/python-trio/trio/issues/853>`__)
- Fixed support for multiple tasks calling :meth:`trio.Process.wait`
  simultaneously; on kqueue platforms it would previously raise an exception. (`#854 <https://github.com/python-trio/trio/issues/854>`__)
- :exc:`trio.Cancelled` exceptions now always propagate until they reach
  the outermost unshielded cancelled scope, even if more cancellations
  occur or shielding is changed between when the :exc:`~trio.Cancelled`
  is delivered and when it is caught. (`#860 <https://github.com/python-trio/trio/issues/860>`__)
- If you have a :class:`SocketStream` that's already been closed, then
  ``await socket_stream.send_all(b"")`` will now correctly raise
  :exc:`ClosedResourceError`. (`#874 <https://github.com/python-trio/trio/issues/874>`__)
- Simplified the Windows subprocess pipe ``send_all`` code, and in the
  process fixed a theoretical bug where closing a pipe at just the wrong
  time could produce errors or cause data to be redirected to the wrong
  pipe. (`#883 <https://github.com/python-trio/trio/issues/883>`__)


Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- Deprecate ``trio.open_cancel_scope`` in favor of :class:`trio.CancelScope`,
  which more clearly reflects that creating a cancel scope is just an ordinary
  object construction and does not need to be immediately paired with entering it. (`#607 <https://github.com/python-trio/trio/issues/607>`__)
- The submodules ``trio.ssl`` and ``trio.subprocess`` are now deprecated.
  Their nontrivial contents (:class:`~trio.Process`, :class:`~trio.SSLStream`,
  and :class:`~trio.SSLListener`) have been moved to the main :mod:`trio`
  namespace. For the numerous constants, exceptions, and other helpers
  that were previously reexported from the standard :mod:`ssl` and
  :mod:`subprocess` modules, you should now use those modules directly. (`#852 <https://github.com/python-trio/trio/issues/852>`__)
- Remove all the APIs deprecated in 0.9.0 or earlier (``trio.Queue``,
  ``trio.catch_signals()``, ``trio.BrokenStreamError``, and
  ``trio.ResourceBusyError``), except for ``trio.hazmat.UnboundedQueue``,
  which stays for now since it is used by the obscure lowlevel functions
  ``monitor_completion_queue()`` and ``monitor_kevent()``. (`#918 <https://github.com/python-trio/trio/issues/918>`__)


Miscellaneous internal changes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Entering a cancel scope whose deadline is in the past now immediately
  cancels it, so :exc:`~trio.Cancelled` will be raised by the first
  checkpoint in the cancel scope rather than the second one.
  This also affects constructs like ``with trio.move_on_after(0):``. (`#320 <https://github.com/python-trio/trio/issues/320>`__)


Trio 0.10.0 (2019-01-07)
------------------------

Features
~~~~~~~~

- Initial :ref:`subprocess support <subprocess>`. Add
  :class:`trio.subprocess.Process <trio.Process>`, an async wrapper around the stdlib
  :class:`subprocess.Popen` class, which permits spawning subprocesses and
  communicating with them over standard Trio streams. ``trio.subprocess``
  also reexports all the stdlib :mod:`subprocess` exceptions and constants for
  convenience. (`#4 <https://github.com/python-trio/trio/issues/4>`__)
- You can now create an unbounded :class:`CapacityLimiter` by initializing with
  `math.inf` (`#618 <https://github.com/python-trio/trio/issues/618>`__)
- New :mod:`trio.hazmat <trio.lowlevel>` features to allow cleanly switching live coroutine
  objects between Trio and other coroutine runners. Frankly, we're not even
  sure this is a good idea, but we want to `try it out in trio-asyncio
  <https://github.com/python-trio/trio-asyncio/issues/42>`__, so here we are.
  For details see :ref:`live-coroutine-handoff`. (`#649
  <https://github.com/python-trio/trio/issues/649>`__)


Bugfixes
~~~~~~~~

- Fixed a race condition on macOS, where Trio's TCP listener would crash if an
  incoming TCP connection was closed before the listener had a chance to accept
  it. (`#609 <https://github.com/python-trio/trio/issues/609>`__)
- :func:`trio.open_tcp_stream()` has been refactored to clean up unsuccessful
  connection attempts more reliably. (`#809
  <https://github.com/python-trio/trio/issues/809>`__)


Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- Remove the APIs deprecated in 0.5.0. (``ClosedStreamError``,
  ``ClosedListenerError``, ``Result``) (`#812
  <https://github.com/python-trio/trio/issues/812>`__)


Miscellaneous internal changes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- There are a number of methods on :class:`trio.ssl.SSLStream <trio.SSLStream>`
  that report information about the negotiated TLS connection, like
  ``selected_alpn_protocol``, and thus cannot succeed until after the handshake
  has been performed. Previously, we returned None from these methods, like the
  stdlib :mod:`ssl` module does, but this is confusing, because that can also
  be a valid return value. Now we raise :exc:`trio.ssl.NeedHandshakeError
  <trio.NeedHandshakeError>`
  instead. (`#735 <https://github.com/python-trio/trio/issues/735>`__)


Trio 0.9.0 (2018-10-12)
-----------------------

Features
~~~~~~~~

- New and improved APIs for inter-task communication:
  :class:`trio.abc.SendChannel`, :class:`trio.abc.ReceiveChannel`, and
  :func:`trio.open_memory_channel` (which replaces ``trio.Queue``). This
  interface uses separate "sender" and "receiver" objects, for
  consistency with other communication interfaces like
  :class:`~trio.abc.Stream`. Also, the two objects can now be closed
  individually, making it much easier to gracefully shut down a channel.
  Also, check out the nifty ``clone`` API to make it easy to manage
  shutdown in multiple-producer/multiple-consumer scenarios. Also, the
  API has been written to allow for future channel implementations that
  send objects across process boundaries. Also, it supports unbounded
  buffering if you really need it. Also, help I can't stop writing also.
  See :ref:`channels` for more details. (`#497
  <https://github.com/python-trio/trio/issues/497>`__)


Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- ``trio.Queue`` and ``trio.hazmat.UnboundedQueue`` have been deprecated, in
  favor of :func:`trio.open_memory_channel`. (`#497
  <https://github.com/python-trio/trio/issues/497>`__)


Trio 0.8.0 (2018-10-01)
-----------------------

Features
~~~~~~~~

- Trio's default internal clock is now based on :func:`time.perf_counter`
  instead of :func:`time.monotonic`. This makes time-keeping more precise on
  Windows, and has no effect on other platforms. (`#33
  <https://github.com/python-trio/trio/issues/33>`__)
- Reworked :mod:`trio`, :mod:`trio.testing`, and :mod:`trio.socket` namespace
  construction, making them more understandable by static analysis tools. This
  should improve tab completion in editors, reduce false positives from pylint,
  and is a first step towards providing type hints. (`#542
  <https://github.com/python-trio/trio/issues/542>`__)


Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- ``ResourceBusyError`` is now a deprecated alias for the new
  :exc:`BusyResourceError`, and ``BrokenStreamError`` is a deprecated alias for
  the new :exc:`BrokenResourceError`. (`#620
  <https://github.com/python-trio/trio/issues/620>`__)


Trio 0.7.0 (2018-09-03)
-----------------------

Features
~~~~~~~~

- The length of typical exception traces coming from Trio has been
  greatly reduced. This was done by eliminating many of the exception
  frames related to details of the implementation. For examples, see
  the `blog post
  <https://vorpus.org/blog/beautiful-tracebacks-in-trio-v070/>`__.
  (`#56 <https://github.com/python-trio/trio/issues/56>`__)
- New and improved signal catching API: :func:`open_signal_receiver`. (`#354
  <https://github.com/python-trio/trio/issues/354>`__)
- The low level ``trio.hazmat.wait_socket_readable``,
  ``wait_socket_writable``, and
  ``notify_socket_close`` now work on bare socket descriptors,
  instead of requiring a :func:`socket.socket` object. (`#400
  <https://github.com/python-trio/trio/issues/400>`__)
- If you're using :func:`trio.hazmat.wait_task_rescheduled <trio.lowlevel.wait_task_rescheduled>` and other low-level
  routines to implement a new sleeping primitive, you can now use the new
  :data:`trio.hazmat.Task.custom_sleep_data <trio.lowlevel.Task.custom_sleep_data>` attribute to pass arbitrary data
  between the sleeping task, abort function, and waking task. (`#616
  <https://github.com/python-trio/trio/issues/616>`__)


Bugfixes
~~~~~~~~

- Prevent crashes when used with Sentry (raven-python). (`#599
  <https://github.com/python-trio/trio/issues/599>`__)
- The nursery context manager was rewritten to avoid use of
  ``@asynccontextmanager`` and ``@async_generator``. This reduces extraneous frames
  in exception traces and addresses bugs regarding `StopIteration` and
  `StopAsyncIteration` exceptions not propagating correctly. (`#612
  <https://github.com/python-trio/trio/issues/612>`__)
- Updates the formatting of exception messages raised by
  :func:`trio.open_tcp_stream` to correctly handle a hostname passed in as
  bytes, by converting the hostname to a string. (`#633
  <https://github.com/python-trio/trio/issues/633>`__)


Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- ``trio.catch_signals`` has been deprecated in favor of
  :func:`open_signal_receiver`. The main differences are: it takes
  \*-args now to specify the list of signals (so
  ``open_signal_receiver(SIGINT)`` instead of
  ``catch_signals({SIGINT})``), and, the async iterator now yields
  individual signals, instead of "batches" (`#354
  <https://github.com/python-trio/trio/issues/354>`__)
- Remove all the APIs deprecated in 0.3.0 and 0.4.0. (`#623
  <https://github.com/python-trio/trio/issues/623>`__)


Trio 0.6.0 (2018-08-13)
-----------------------

Features
~~~~~~~~

- Add :func:`trio.hazmat.WaitForSingleObject <trio.lowlevel.WaitForSingleObject>` async function to await Windows
  handles. (`#233 <https://github.com/python-trio/trio/issues/233>`__)
- The `sniffio <https://github.com/python-trio/sniffio>`__ library can now
  detect when Trio is running. (`#572
  <https://github.com/python-trio/trio/issues/572>`__)


Bugfixes
~~~~~~~~

- Make trio.socket._SocketType.connect *always* close the socket on
  cancellation (`#247 <https://github.com/python-trio/trio/issues/247>`__)
- Fix a memory leak in :class:`trio.CapacityLimiter`, that could occurr when
  ``acquire`` or ``acquire_on_behalf_of`` was cancelled. (`#548
  <https://github.com/python-trio/trio/issues/548>`__)
- Some version of macOS have a buggy ``getaddrinfo`` that was causing spurious
  test failures; we now detect those systems and skip the relevant test when
  found. (`#580 <https://github.com/python-trio/trio/issues/580>`__)
- Prevent crashes when used with Sentry (raven-python). (`#599
  <https://github.com/python-trio/trio/issues/599>`__)


Trio 0.5.0 (2018-07-20)
-----------------------

Features
~~~~~~~~

- Suppose one task is blocked trying to use a resource – for example, reading
  from a socket – and while it's doing this, another task closes the resource.
  Previously, this produced undefined behavior. Now, closing a resource causes
  pending operations on that resource to terminate immediately with a
  :exc:`ClosedResourceError`. ``ClosedStreamError`` and ``ClosedListenerError``
  are now aliases for :exc:`ClosedResourceError`, and deprecated. For this to
  work, Trio needs to know when a resource has been closed. To facilitate this,
  new functions have been added: ``trio.hazmat.notify_fd_close`` and
  ``trio.hazmat.notify_socket_close``. If you're using Trio's built-in
  wrappers like :class:`~trio.SocketStream` or :mod:`trio.socket`, then you don't
  need to worry about this, but if you're using the low-level functions like
  :func:`trio.hazmat.wait_readable <trio.lowlevel.wait_readable>`, you should make sure to call these
  functions at appropriate times. (`#36
  <https://github.com/python-trio/trio/issues/36>`__)
- Tasks created by :func:`~trio.lowlevel.spawn_system_task` now no longer inherit
  the creator's :mod:`contextvars` context, instead using one created at
  :func:`~trio.run`. (`#289
  <https://github.com/python-trio/trio/issues/289>`__)
- Add support for ``trio.Queue`` with ``capacity=0``. Queue's implementation
  is also faster now. (`#473
  <https://github.com/python-trio/trio/issues/473>`__)
- Switch to using standalone `Outcome
  <https://github.com/python-trio/outcome>`__ library for Result objects.
  (`#494 <https://github.com/python-trio/trio/issues/494>`__)

Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- ``trio.hazmat.Result``, ``trio.hazmat.Value`` and
  ``trio.hazmat.Error`` have been replaced by the equivalent
  classes in the `Outcome <https://github.com/python-trio/outcome>`__ library.

Trio 0.4.0 (2018-04-10)
-----------------------

Features
~~~~~~~~

- Add unix client socket support. (`#401
  <https://github.com/python-trio/trio/issues/401>`__)
- Add support for :mod:`contextvars` (see :ref:`task-local storage
  <task-local-storage>`), and add :class:`trio.hazmat.RunVar <trio.lowlevel.RunVar>` as a similar API
  for run-local variables. Deprecate ``trio.TaskLocal`` and
  ``trio.hazmat.RunLocal`` in favor of these new APIs. (`#420
  <https://github.com/python-trio/trio/issues/420>`__)
- Add :func:`trio.hazmat.current_root_task <trio.lowlevel.current_root_task>` to get the root task. (`#452
  <https://github.com/python-trio/trio/issues/452>`__)


Bugfixes
~~~~~~~~

- Fix KeyboardInterrupt handling when threading state has been modified by a
  3rd-party library. (`#461
  <https://github.com/python-trio/trio/issues/461>`__)


Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- Attempting to explicitly raise :exc:`trio.Cancelled` will cause a :exc:`RuntimeError`.
  :meth:`cancel_scope.cancel() <trio.CancelScope.cancel>` should
  be used instead. (`#342 <https://github.com/python-trio/trio/issues/342>`__)


Miscellaneous internal changes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Simplify implementation of primitive traps like :func:`~trio.lowlevel.wait_task_rescheduled`
  (`#395 <https://github.com/python-trio/trio/issues/395>`__)


Trio 0.3.0 (2017-12-28)
-----------------------

Features
~~~~~~~~

- **Simplified nurseries**: In Trio, the rule used to be that "parenting is a
  full time job", meaning that after a task opened a nursery and spawned some
  children into it, it had to immediately block in ``__aexit__`` to supervise
  the new children, or else exception propagation wouldn't work. Also there was
  some elaborate machinery to let you replace this supervision logic with your
  own custom supervision logic. Thanks to new advances in task-rearing
  technology, **parenting is no longer a full time job!** Now the supervision
  happens automatically in the background, and essentially the body of a
  ``async with trio.open_nursery()`` block acts just like a task running inside
  the nursery. This is important: it makes it possible for libraries to
  abstract over nursery creation. For example, if you have a Websocket library
  that needs to run a background task to handle Websocket pings, you can now do
  that with ``async with open_websocket(...) as ws: ...``, and that can run a
  task in the background without your users having to worry about parenting it.
  And don't worry, you can still make custom supervisors; it turned out all
  that spiffy machinery was actually redundant and didn't provide much value.
  (`#136 <https://github.com/python-trio/trio/issues/136>`__)
- Trio socket methods like ``bind`` and ``connect`` no longer require
  "pre-resolved" numeric addresses; you can now pass regular hostnames and Trio
  will implicitly resolve them for you. (`#377
  <https://github.com/python-trio/trio/issues/377>`__)


Bugfixes
~~~~~~~~

- Fixed some corner cases in Trio socket method implicit name resolution to
  better match stdlib behavior. Example: ``sock.bind(("", port))`` now binds to
  the wildcard address instead of raising an error. (`#277
  <https://github.com/python-trio/trio/issues/277>`__)


Deprecations and Removals
~~~~~~~~~~~~~~~~~~~~~~~~~

- Removed everything that was deprecated in 0.2.0; see the 0.2.0
  release notes below for details.
- As was foretold in the v0.2.0 release notes, the ``bind`` method on Trio
  sockets is now async. Please update your calls or – better yet – switch to
  our shiny new high-level networking API, like :func:`serve_tcp`. (`#241
  <https://github.com/python-trio/trio/issues/241>`__)
- The ``resolve_local_address`` and ``resolve_remote_address`` methods
  on Trio sockets have been deprecated; these are unnecessary now that
  you can just pass your hostnames directly to the socket methods you
  want to use. (`#377
  <https://github.com/python-trio/trio/issues/377>`__)


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

* The new nursery :meth:`~Nursery.start` method makes it
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
  :func:`trio.open_ssl_over_tcp_listeners`, and ``trio.ssl``.

  Interesting fact: the test suite for ``trio.ssl`` has so far
  found bugs in CPython's ssl module, PyPy's ssl module, PyOpenSSL,
  and OpenSSL. (``trio.ssl`` doesn't use PyOpenSSL.) Trio's test
  suite is fairly thorough.

* You know thread-local storage? Well, Trio now has an equivalent:
  :ref:`task-local storage <task-local-storage>`. There's also the
  related, but more obscure, run-local storage; see
  :class:`~trio.lowlevel.RunLocal`. (`#2
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
  :class:`~trio.SSLStream` wrapped around a
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
    ``run_sync_in_worker_thread``

  * We took the opportunity to refactor ``run_in_trio_thread`` and
    ``await_in_trio_thread`` into the new class
    ``trio.BlockingTrioPortal``

  * The hazmat function ``current_call_soon_thread_and_signal_safe``
    is being replaced by :class:`trio.hazmat.TrioToken <trio.lowlevel.TrioToken>`

  See `#68 <https://github.com/python-trio/trio/issues/68>`__ for
  details.

* ``trio.Queue``\'s ``join`` and ``task_done`` methods are
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
  main :mod:`trio` namespace and into :mod:`trio.hazmat <trio.lowlevel>`:

  * ``trio.Task`` → :class:`trio.hazmat.Task <trio.lowlevel.Task>`
  * ``trio.current_task`` → :func:`trio.hazmat.current_task <trio.lowlevel.current_task>`
  * ``trio.Result`` → ``trio.hazmat.Result``
  * ``trio.Value`` → ``trio.hazmat.Value``
  * ``trio.Error`` → ``trio.hazmat.Error``
  * ``trio.UnboundedQueue`` → ``trio.hazmat.UnboundedQueue``

  In addition, several introspection attributes are being renamed:

  * ``nursery.children`` → ``nursery.child_tasks``
  * ``task.parent_task`` → use ``task.parent_nursery.parent_task`` instead

  See `#136 <https://github.com/python-trio/trio/issues/136>`__ for
  more details.

* To consolidate introspection functionality in :mod:`trio.hazmat <trio.lowlevel>`,
  the following functions are moving:

  * ``trio.current_clock`` → :func:`trio.hazmat.current_clock <trio.lowlevel.current_clock>`
  * ``trio.current_statistics`` →
    :func:`trio.hazmat.current_statistics <trio.lowlevel.current_statistics>`

  See `#317 <https://github.com/python-trio/trio/issues/317>`__ for
  more details.

* It was decided that 0.1.0's "yield point" terminology was confusing;
  we now use :ref:`"checkpoint" <checkpoints>` instead. As part of
  this, the following functions in :mod:`trio.hazmat <trio.lowlevel>` are changing
  names:

  * ``yield_briefly`` → :func:`~trio.hazmat.checkpoint <trio.lowlevel.checkpoint>`
  * ``yield_briefly_no_cancel`` → :func:`~trio.lowlevel.cancel_shielded_checkpoint`
  * ``yield_if_cancelled`` → :func:`~trio.lowlevel.checkpoint_if_cancelled`
  * ``yield_indefinitely`` → :func:`~trio.lowlevel.wait_task_rescheduled`

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
  instrumentation at run-time, see :func:`trio.hazmat.add_instrument <trio.lowlevel.add_instrument>`
  and :func:`trio.hazmat.remove_instrument <trio.lowlevel.remove_instrument>` (`#257
  <https://github.com/python-trio/trio/issues/257>`__)

Unfortunately, a limitation in PyPy3 5.8 breaks our deprecation
handling for some renames. (Attempting to use the old names will give
an unhelpful error instead of a helpful warning.) This does not affect
CPython, or PyPy3 5.9+.


Other changes
~~~~~~~~~~~~~

* ``run_sync_in_worker_thread`` now has a :ref:`robust mechanism
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

* New exception ``ResourceBusyError``

* The :class:`trio.hazmat.ParkingLot <trio.lowlevel.ParkingLot>` class (which is used to
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
  for the :mod:`trio` and :mod:`trio.hazmat <trio.lowlevel>` modules (`#314
  <https://github.com/python-trio/trio/issues/314>`__)

* Trio now uses `yapf <https://github.com/google/yapf>`__ to
  standardize formatting across the source tree, so we never have to
  think about whitespace again.

* Many documentation improvements


Trio 0.1.0 (2017-03-10)
-----------------------

* Initial release.
