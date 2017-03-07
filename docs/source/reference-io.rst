I/O in Trio
===========

Sockets and networking
----------------------

.. module:: trio.socket

The :mod:`trio.socket` module provides trio's basic networking API.


:mod:`trio.socket`\'s top-level exports
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Generally, :mod:`trio.socket`\'s API mirrors that of the standard
library :mod:`socket` module. Most constants (like ``SOL_SOCKET``) and
simple utilities (like :func:`~socket.inet_aton`) are simply
re-exported unchanged. But there are also some differences:

The following functions have similar interfaces to their standard
library version, but are modified to return trio socket objects
instead of stdlib socket objects:

* :func:`~socket.socket`
* :func:`~socket.socketpair`
* :func:`~socket.fromfd`
* :func:`~socket.fromshare`

In addition, there is a new function to directly convert a standard
library socket into a trio socket:

.. autofunction:: from_stdlib_socket

The following functions have identical interfaces to their standard
library version, but are now ``async`` functions, so you need to use
``await`` to call them:

* :func:`~socket.getaddrinfo`
* :func:`~socket.getnameinfo`
* :func:`~socket.getfqdn`

We intentionally DO NOT include some obsolete, redundant, or broken
features:

* :func:`~socket.gethostbyname`, :func:`~socket.gethostbyname_ex`,
  :func:`~socket.gethostbyaddr`: obsolete; use
  :func:`~socket.getaddrinfo` and :func:`~socket.getnameinfo` instead.

* :func:`~socket.getdefaulttimeout`,
  :func:`~socket.setdefaulttimeout`: Use trio's standard support for
  :ref:`cancellation`.

* On Windows, ``SO_REUSEADDR`` is not exported, because it's a trap:
  the name is the same as Unix ``SO_REUSEADDR``, but the semantics are
  `different and extremely broken
  <https://msdn.microsoft.com/en-us/library/windows/desktop/ms740621(v=vs.85).aspx>`__. In
  the very rare cases where you actually want ``SO_REUSEADDR`` on
  Windows, then it can still be accessed from the standard library's
  :mod:`socket` module.


Socket objects
~~~~~~~~~~~~~~

.. class:: SocketType()

   Trio socket objects are overall very similar to the :ref:`standard
   library socket objects <python:socket-objects>`, with a few
   important differences:

   **Async all the things:** Most obviously, everything is made
   "trio-style": blocking methods become async methods, and the
   following attributes are *not* supported:

   * :meth:`~socket.socket.setblocking`: trio sockets always act like
     blocking sockets; if you need to read/write from multiple sockets
     at once, then create multiple tasks.
   * :meth:`~socket.socket.settimeout`: see :ref:`cancellation` instead.
   * :meth:`~socket.socket.makefile`: Python's file-like API is
     synchronous, so it can't be implemented on top of an async
     socket.

   **No implicit name resolution:** In the standard library
   :mod:`socket` API, there are number of methods that take network
   addresses as arguments. When given a numeric address this is fine::

      # OK
      sock.bind(("127.0.0.1", 80))
      sock.connect(("2607:f8b0:4000:80f::200e", 80))

   But in the standard library, these methods also accept hostnames,
   and in this case implicitly trigger a DNS lookup to find the IP
   address::

      # Might block!
      sock.bind(("localhost", 80))
      sock.connect(("google.com", 80))

   This is problematic because DNS lookups are a blocking operation.

   For simplicity, trio forbids such usages: hostnames must be
   "pre-resolved" to numeric addresses before they are passed to
   socket methods like :meth:`bind` or :meth:`connect`. In most cases
   this can be easily accomplished by calling either
   :meth:`resolve_local_address` or :meth:`resolve_remote_address`.

   **Modern defaults:** And finally, we took the opportunity to update
   the defaults for several socket options that were stuck in the
   1980s. You can always use :meth:`setsockopt` to change these back,
   but for trio sockets:

   1. Everywhere except Windows, ``SO_REUSEADDR`` is enabled by
      default. This is almost always what you want, but if you're in
      one of the `rare cases
      <https://idea.popcount.org/2014-04-03-bind-before-connect/>`__
      where this is undesireable then you can always disable
      ``SO_REUSEADDR`` manually::

         sock.setsockopt(trio.socket.SOL_SOCKET, trio.socket.SO_REUSEADDR, False)

      On Windows, ``SO_EXCLUSIVEADDR`` is enabled by
      default. Unfortunately, this means that if you stop and restart
      a server you may have trouble reacquiring listen ports (i.e., it
      acts like Unix without ``SO_REUSEADDR``).  To get the Unix-style
      ``SO_REUSEADDR`` semantics on Windows, you can disable
      ``SO_EXCLUSIVEADDR``::

         sock.setsockopt(trio.socket.SOL_SOCKET, trio.socket.SO_EXCLUSIVEADDR, False)

      but be warned that `this may leave your application vulnerable
      to port hijacking attacks
      <https://msdn.microsoft.com/en-us/library/windows/desktop/ms740621(v=vs.85).aspx>`__.

   2. ``TCP_NODELAY`` is enabled by default.

   3. ``IPV6_V6ONLY`` is disabled, i.e., by default on dual-stack
      hosts a ``AF_INET6`` socket is able to communicate with both
      IPv4 and IPv6 peers, where the IPv4 peers appear to be in the
      `"IPv4-mapped" portion of IPv6 address space
      <http://www.tcpipguide.com/free/t_IPv6IPv4AddressEmbedding-2.htm>`__. To
      make an IPv6-only socket, use something like::

        sock = trio.socket.socket(trio.socket.AF_INET6)
        sock.setsockopt(trio.socket.IPPROTO_IPV6, trio.socket.IPV6_V6ONLY, True)

      This makes trio applications behave more consistently across
      different environments.

   4. On platforms where it's supported (recent Linux and recent
      MacOS), ``TCP_NOTSENT_LOWAT`` is enabled with a reasonable
      buffer size (currently 16 KiB).

   See `issue #72 <https://github.com/njsmith/trio/issues/72>`__ for
   discussion of these defaults.

   .. automethod:: resolve_local_address
   .. automethod:: resolve_remote_address

   .. method:: connect

   .. method:: bind

   .. method:: send

   .. method:: recv

   .. method:: setsockopt
   .. method:: getsockopt

   .. method:: sendfile

      `Not implemented yet! <https://github.com/njsmith/trio/issues/45>`__

   All methods and attributes *not* mentioned above are identical to
   their equivalents in :func:`socket.socket`.


The abstract Stream API
-----------------------

(this is currently more of a sketch than something actually useful,
`see issue #73 <https://github.com/njsmith/trio/issues/73>`__)

.. currentmodule:: trio

.. autoclass:: AsyncResource
   :members:
   :undoc-members:

.. autoclass:: SendStream
   :members:
   :undoc-members:

.. autoclass:: RecvStream
   :members:
   :undoc-members:

.. autoclass:: Stream
   :members:
   :undoc-members:


TLS support
-----------

`Not implemented yet! <https://github.com/njsmith/trio/issues/9>`__


Async disk I/O
--------------

`Not implemented yet! <https://github.com/njsmith/trio/issues/20>`__


Subprocesses
------------

`Not implemented yet! <https://github.com/njsmith/trio/issues/4>`__


Signals
-------

.. currentmodule:: trio

.. autofunction:: catch_signals
   :with: batched_signal_aiter
