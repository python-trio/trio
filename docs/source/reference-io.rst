.. currentmodule:: trio

I/O in Trio
===========

.. note::

   Please excuse our dust! `[insert geocities construction worker gif
   here] <http://www.textfiles.com/underconstruction/>`__

   You're looking at the documentation for trio's development branch,
   which is currently about half-way through implementing a proper
   high-level networking API. If you want to know how to do networking
   in trio *right now*, then you might want to jump down to read about
   :mod:`trio.socket`, which is the already-working lower-level
   API. Alternatively, you can read on for a (somewhat disorganized)
   preview of coming attractions.

.. _abstract-stream-api:

The abstract Stream API
-----------------------

Trio provides a set of abstract base classes that define a standard
interface for unidirectional and bidirectional byte streams.

Why is this useful? Because it lets you write generic protocol
implementations that can work over arbitrary transports, and easily
create complex transport configurations. Here's some examples:

* :class:`trio.SocketStream` wraps a raw socket (like a TCP connection
  over the network), and converts it to the standard stream interface.

* :class:`trio.ssl.SSLStream` is a "stream adapter" that can take any
  object that implements the :class:`trio.abc.Stream` interface, and
  convert it into an encrypted stream. In trio the standard way to
  speak SSL over the network is to wrap an
  :class:`~trio.ssl.SSLStream` around a :class:`~trio.SocketStream`.

* If you spawn a subprocess then you can get a
  :class:`~trio.abc.SendStream` that lets you write to its stdin, and
  a :class:`~trio.abc.ReceiveStream` that lets you read from its
  stdout. If for some reason you wanted to speak SSL to a subprocess,
  you could use a :class:`StapledStream` to combine its stdin/stdout
  into a single bidirectional :class:`~trio.abc.Stream`, and then wrap
  that in an :class:`~trio.ssl.SSLStream`::

     ssl_context = trio.ssl.create_default_context()
     ssl_context.check_hostname = False
     s = SSLStream(StapledStream(process.stdin, process.stdout), ssl_context)

  [Note: subprocess support is not implemented yet, but that's the
  plan. Unless it is implemented, and I forgot to remove this note.]

* It sometimes happens that you want to connect to an HTTPS server,
  but you have to go through a web proxy... and the proxy also uses
  HTTPS. So you end up having to do `SSL-on-top-of-SSL
  <https://daniel.haxx.se/blog/2016/11/26/https-proxy-with-curl/>`__. In
  trio this is trivial – just wrap your first
  :class:`~trio.ssl.SSLStream` in a second
  :class:`~trio.ssl.SSLStream`::

     # Get a raw SocketStream connection to the proxy:
     s0 = await open_tcp_stream("proxy", 443)

     # Set up SSL connection to proxy:
     s1 = SSLStream(s0, proxy_ssl_context, server_hostname="proxy")
     # Request a connection to the website
     await s1.send_all(b"CONNECT website:443 / HTTP/1.0\r\n")
     await check_CONNECT_response(s1)

     # Set up SSL connection to the real website. Notice that s1 is
     # already an SSLStream object, and here we're wrapping a second
     # SSLStream object around it.
     s2 = SSLStream(s1, website_ssl_context, server_hostname="website")
     # Make our request
     await s2.send_all("GET /index.html HTTP/1.0\r\n")
     ...

* The :mod:`trio.testing` module provides a set of :ref:`flexible
  in-memory stream object implementations <testing-streams>`, so if
  you have a protocol implementation to test then you can can spawn
  two tasks, set up a virtual "socket" connecting them, and then do
  things like inject random-but-repeatable delays into the connection.


Abstract base classes
~~~~~~~~~~~~~~~~~~~~~

.. currentmodule:: trio.abc

.. autoclass:: trio.abc.AsyncResource
   :members:

.. autoclass:: trio.abc.SendStream
   :members:
   :show-inheritance:

.. autoclass:: trio.abc.ReceiveStream
   :members:
   :show-inheritance:

.. autoclass:: trio.abc.Stream
   :members:
   :show-inheritance:

.. autoclass:: trio.abc.HalfCloseableStream
   :members:
   :show-inheritance:

.. currentmodule:: trio

.. autoexception:: BrokenStreamError

.. autoexception:: ClosedStreamError


Generic stream implementations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Trio currently provides one generic utility class for working with
streams. And if you want to test code that's written against the
streams interface, you should also check out :ref:`testing-streams` in
:mod:`trio.testing`.

.. autoclass:: StapledStream
   :members:
   :show-inheritance:


Sockets and networking
~~~~~~~~~~~~~~~~~~~~~~

The high-level network interface is built on top of our stream
abstraction.

.. autoclass:: SocketStream
   :members:
   :show-inheritance:

.. autofunction:: socket_stream_pair


SSL / TLS support
~~~~~~~~~~~~~~~~~

.. module:: trio.ssl

The :mod:`trio.ssl` module implements SSL/TLS support for Trio, using
the standard library :mod:`ssl` module. It re-exports most of
:mod:`ssl`\´s API, with the notable exception is
:class:`ssl.SSLContext`, which has unsafe defaults; if you really want
to use :class:`ssl.SSLContext` you can import it from :mod:`ssl`, but
normally you should create your contexts using
:func:`trio.ssl.create_default_context <ssl.create_default_context>`.

Instead of using :meth:`ssl.SSLContext.wrap_socket`, though, you
create a :class:`SSLStream`:

.. autoclass:: SSLStream
   :show-inheritance:
   :members:


.. module:: trio.socket

Low-level networking with :mod:`trio.socket`
---------------------------------------------

The :mod:`trio.socket` module provides trio's basic low-level
networking API. If you're doing ordinary things with stream-oriented
connections over IPv4/IPv6/Unix domain sockets, then you probably want
to stick to the high-level API described above. If you want to use
UDP, or exotic address families like ``AF_BLUETOOTH``, or otherwise
get direct access to all the quirky bits of your system's networking
API, then you're in the right place.


Top-level exports
~~~~~~~~~~~~~~~~~

Generally, the API exposed by :mod:`trio.socket` mirrors that of the
standard library :mod:`socket` module. Most constants (like
``SOL_SOCKET``) and simple utilities (like :func:`~socket.inet_aton`)
are simply re-exported unchanged. But there are also some differences,
which are described here.

.. function:: socket(...)
              socketpair(...)
              fromfd(...)
              fromshare(...)

   Trio provides analogues to all the standard library functions that
   return socket objects; their interface is identical, except that
   they're modified to return trio socket objects instead.

In addition, there is a new function to directly convert a standard
library socket into a trio socket:

.. autofunction:: from_stdlib_socket

Unlike :func:`socket.socket`, :func:`trio.socket.socket` is a
function, not a class; if you want to check whether an object is a
trio socket, use:

.. autofunction:: is_trio_socket

For name lookup, Trio provides the standard functions, but with some
changes:

.. autofunction:: getaddrinfo

.. autofunction:: getnameinfo

.. autofunction:: getprotobyname

Trio intentionally DOES NOT include some obsolete, redundant, or
broken features:

* :func:`~socket.gethostbyname`, :func:`~socket.gethostbyname_ex`,
  :func:`~socket.gethostbyaddr`: obsolete; use
  :func:`~socket.getaddrinfo` and :func:`~socket.getnameinfo` instead.

* :func:`~socket.getservbyport`: obsolete and `buggy
  <https://bugs.python.org/issue30482>`__; instead, do::

     _, service_name = await getnameinfo((127.0.0.1, port), NI_NUMERICHOST))

* :func:`~socket.getservbyname`: obsolete and `buggy
  <https://bugs.python.org/issue30482>`__; instead, do::

     await getaddrinfo(None, service_name)

* :func:`~socket.getfqdn`: obsolete; use :func:`getaddrinfo` with the
  ``AI_CANONNAME`` flag.

* :func:`~socket.getdefaulttimeout`,
  :func:`~socket.setdefaulttimeout`: instead, use trio's standard
  support for :ref:`cancellation`.

* On Windows, ``SO_REUSEADDR`` is not exported, because it's a trap:
  the name is the same as Unix ``SO_REUSEADDR``, but the semantics are
  `different and extremely broken
  <https://msdn.microsoft.com/en-us/library/windows/desktop/ms740621(v=vs.85).aspx>`__. In
  the very rare cases where you actually want ``SO_REUSEADDR`` on
  Windows, then it can still be accessed from the standard library's
  :mod:`socket` module.


Socket objects
~~~~~~~~~~~~~~

.. interface:: The trio socket object interface

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

   .. method:: resolve_local_address(address)

      Resolve the given address into a numeric address suitable for
      passing to :meth:`bind`.

      This performs the same address resolution that the standard library
      :meth:`~socket.socket.bind` call would do, taking into account the
      current socket's settings (e.g. if this is an IPv6 socket then it
      returns IPv6 addresses). In particular, a hostname of ``None`` is
      mapped to the wildcard address.

   .. method:: resolve_remote_address(address)

      Resolve the given address into a numeric address suitable for
      passing to :meth:`connect` or similar.

      This performs the same address resolution that the standard library
      :meth:`~socket.socket.connect` call would do, taking into account the
      current socket's settings (e.g. if this is an IPv6 socket then it
      returns IPv6 addresses). In particular, a hostname of ``None`` is
      mapped to the localhost address.

   **Modern defaults:** And finally, we took the opportunity to update
   the defaults for several socket options that were stuck in the
   1980s. You can always use :meth:`~socket.socket.setsockopt` to
   change these back, but for trio sockets:

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

   2. ``IPV6_V6ONLY`` is disabled, i.e., by default on dual-stack
      hosts a ``AF_INET6`` socket is able to communicate with both
      IPv4 and IPv6 peers, where the IPv4 peers appear to be in the
      `"IPv4-mapped" portion of IPv6 address space
      <http://www.tcpipguide.com/free/t_IPv6IPv4AddressEmbedding-2.htm>`__. To
      make an IPv6-only socket, use something like::

        sock = trio.socket.socket(trio.socket.AF_INET6)
        sock.setsockopt(trio.socket.IPPROTO_IPV6, trio.socket.IPV6_V6ONLY, True)

      This makes trio applications behave more consistently across
      different environments.

   See `issue #72 <https://github.com/python-trio/trio/issues/72>`__ for
   discussion of these defaults.

   The following methods are similar to the equivalents in
   :func:`socket.socket`, but have some trio-specific quirks:

   .. method:: bind

      Bind this socket to the given address.

      Unlike the stdlib :meth:`~socket.socket.bind`, this method
      requires a pre-resolved address. See
      :meth:`resolve_local_address`.

   .. method:: connect
      :async:

      Connect the socket to a remote address.

      Similar to :meth:`socket.socket.connect`, except async and
      requiring a pre-resolved address. See
      :meth:`resolve_remote_address`.

      .. warning::

         Due to limitations of the underlying operating system APIs, it is
         not always possible to properly cancel a connection attempt once it
         has begun. If :meth:`connect` is cancelled, and is unable to
         abort the connection attempt, then it will:

         1. forcibly close the socket to prevent accidental re-use
         2. raise :exc:`~trio.Cancelled`.

         tl;dr: if :meth:`connect` is cancelled then the socket is
         left in an unknown state – possibly open, and possibly
         closed. The only reasonable thing to do is to close it.

   .. method:: sendall(data, flags=0)
      :async:

      Send the data to the socket, blocking until all of it has been
      accepted by the operating system.

      ``flags`` are passed on to ``send``.

      Most low-level operations in trio provide a guarantee: if they raise
      :exc:`trio.Cancelled`, this means that they had no effect, so the
      system remains in a known state. This is **not true** for
      :meth:`sendall`. If this operation raises :exc:`trio.Cancelled` (or
      any other exception for that matter), then it may have sent some, all,
      or none of the requested data, and there is no way to know which.

   .. method:: sendfile

      `Not implemented yet! <https://github.com/python-trio/trio/issues/45>`__

   We also keep track of an extra bit of state, because it turns out
   to be useful for :class:`trio.SocketStream`:

   .. attribute:: did_shutdown_SHUT_WR

      This :class:`bool` attribute it True if you've called
      ``sock.shutdown(SHUT_WR)`` or ``sock.shutdown(SHUT_RDWR)``, and
      False otherwise.

   The following methods are identical to their equivalents in
   :func:`socket.socket`, except async, and the ones that take address
   arguments require pre-resolved addresses:

   * :meth:`~socket.socket.accept`
   * :meth:`~socket.socket.recv`
   * :meth:`~socket.socket.recv_into`
   * :meth:`~socket.socket.recvfrom`
   * :meth:`~socket.socket.recvfrom_into`
   * :meth:`~socket.socket.recvmsg` (if available)
   * :meth:`~socket.socket.recvmsg_into` (if available)
   * :meth:`~socket.socket.send`
   * :meth:`~socket.socket.sendto`
   * :meth:`~socket.socket.sendmsg` (if available)

   All methods and attributes *not* mentioned above are identical to
   their equivalents in :func:`socket.socket`:

   * :attr:`~socket.socket.family`
   * :attr:`~socket.socket.type`
   * :attr:`~socket.socket.proto`
   * :meth:`~socket.socket.fileno`
   * :meth:`~socket.socket.listen`
   * :meth:`~socket.socket.getpeername`
   * :meth:`~socket.socket.getsockname`
   * :meth:`~socket.socket.close`
   * :meth:`~socket.socket.shutdown`
   * :meth:`~socket.socket.setsockopt`
   * :meth:`~socket.socket.getsockopt`
   * :meth:`~socket.socket.dup`
   * :meth:`~socket.socket.detach`
   * :meth:`~socket.socket.share`
   * :meth:`~socket.socket.set_inheritable`
   * :meth:`~socket.socket.get_inheritable`


Asynchronous disk I/O
---------------------

.. currentmodule:: trio

.. autofunction:: open_file

.. autofunction:: wrap_file

Asynchronous path objects
~~~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: Path
   :members:

Subprocesses
------------

`Not implemented yet! <https://github.com/python-trio/trio/issues/4>`__


Signals
-------

.. currentmodule:: trio

.. autofunction:: catch_signals
   :with: batched_signal_aiter
