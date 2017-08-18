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

.. currentmodule:: trio

.. autofunction:: aclose_forcefully

.. currentmodule:: trio.abc

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

.. currentmodule:: trio.abc

.. autoclass:: trio.abc.Listener
   :members:
   :show-inheritance:

.. currentmodule:: trio

.. autoexception:: ClosedListenerError



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
   :undoc-members:
   :show-inheritance:

.. autofunction:: open_tcp_stream

.. autofunction:: open_ssl_over_tcp_stream

.. autoclass:: SocketListener
   :members:
   :show-inheritance:

.. autofunction:: open_tcp_listeners

.. autofunction:: open_ssl_over_tcp_listeners


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

And if you're implementing a server, you can use :class:`SSLListener`:

.. autoclass:: SSLListener
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

First, Trio provides analogues to all the standard library functions
that return socket objects; their interface is identical, except that
they're modified to return trio socket objects instead:

.. autofunction:: socket

.. autofunction:: socketpair

.. autofunction:: fromfd

.. function:: fromshare(data)

   Like :func:`socket.fromshare`, but returns a trio socket object.

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

      .. warning:: If two tasks call this method simultaneously on the
         same socket, then their data may end up intermingled on the
         wire. This is almost certainly not what you want. Use the
         highlevel interface instead (:meth:`trio.SocketStream.send_all`);
         it reliably detects this error.

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

.. currentmodule:: trio


.. _async-file-io:

Asynchronous filesystem I/O
---------------------------

Trio provides built-in facilities for performing asynchronous
filesystem operations like reading or renaming a file. Generally, we
recommend that you use these instead of Python's normal synchronous
file APIs. But the tradeoffs here are somewhat subtle: sometimes
people switch to async I/O, and then they're surprised and confused
when they find it doesn't speed up their program. The next section
explains the theory behind async file I/O, to help you better
understand your code's behavior. Or, if you just want to get started,
you can `jump down to the API overview
<ref:async-file-io-overview>`__.


Background: Why is async file I/O useful? The answer may surprise you
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Many people expect that switching to from synchronous file I/O to
async file I/O will always make their program faster. This is not
true! If we just look at total throughput, then async file I/O might
be faster, slower, or about the same, and it depends in a complicated
way on things like your exact patterns of disk access how much RAM you
have. The main motivation for async file I/O is not to improve
throughput, but to **reduce the frequency of latency glitches.**

To understand why, you need to know two things.

First, right now no mainstream operating system offers a generic,
reliable, native API for async file for filesystem operations, so we
have to fake it by using threads (specifically,
:func:`run_in_worker_thread`). This is cheap but isn't free: on a
typical PC, dispatching to a worker thread adds something like ~100 µs
of overhead to each operation. ("µs" is pronounced "microseconds", and
there are 1,000,000 µs in a second. Note that all the numbers here are
going to be rough orders of magnitude to give you a sense of scale; if
you need precise numbers for your environment, measure!)

.. file.read benchmark is notes-to-self/file-read-latency.py
.. Numbers for spinning disks and SSDs are from taking a few random
   recent reviews from http://www.storagereview.com/best_drives and
   looking at their "4K Write Latency" test results for "Average MS"
   and "Max MS":
   http://www.storagereview.com/samsung_ssd_850_evo_ssd_review
   http://www.storagereview.com/wd_black_6tb_hdd_review

And second, the cost of a disk operation is incredibly
bimodal. Sometimes, the data you need is already cached in RAM, and
then accessing it is very, very fast – calling :class:`io.FileIO`\'s
``read`` method on a cached file takes on the order of ~1 µs. But when
the data isn't cached, then accessing it is much, much slower: the
average is ~100 µs for SSDs and ~10,000 µs for spinning disks, and if
you look at tail latencies then for both types of storage you'll see
cases where occasionally some operation will be 10x or 100x slower
than average. And that's assuming your program is the only thing
trying to use that disk – if you're on some oversold cloud VM fighting
for I/O with other tenants then who knows what will happen. And some
operations can require multiple disk accesses.

Putting these together: if your data is in RAM then it should be clear
that using a thread is a terrible idea – if you add 100 µs of overhead
to a 1 µs operation, then that's a 100x slowdown! On the other hand,
if your data's on a spinning disk, then using a thread is *great* –
instead of blocking the main thread and all tasks for 10,000 µs, we
only block them for 100 µs and can spend the rest of that time running
other tasks to get useful work done, which can effectively be a 100x
speedup.

But here's the problem: for any individual I/O operation, there's no
way to know in advance whether it's going to be one of the fast ones
or one of the slow ones, so you can't pick and choose. When you switch
to async file I/O, it makes all the fast operations slower, and all
the slow operations faster. Is that a win? In terms of overall speed,
it's hard to say: it depends what kind of disks you're using and your
kernel's disk cache hit rate, which in turn depends on your file
access patterns, how much spare RAM you have, the load on your
service, ... all kinds of things. If the answer is important to you,
then there's no substitute for measuring your code's actual behavior
in your actual deployment environment. But what we *can* say is that
async disk I/O makes performance much more predictable across a wider
range of runtime conditions.

**If you're not sure what to do, then we recommend that you use async
disk I/O by default,** because it makes your code more robust when
conditions are bad, especially with regards to tail latencies; this
improves the chances that what your users see matches what you saw in
testing. Blocking the main thread stops *all* tasks from running for
that time. 10,000 µs is 10 ms, and it doesn't take many 10 ms glitches
to start adding up to `real money
<https://google.com/search?q=latency+cost>`__; async disk I/O can help
prevent those. Just don't expect it to be magic, and be aware of the
tradeoffs.


.. _async-file-io-overview:

API overview
~~~~~~~~~~~~

If you want to perform general filesystem operations like creating and
listing directories, renaming files, or checking file metadata – or if
you just want a friendly way to work with filesystem paths – then you
want :class:`trio.Path`. It's an asyncified replacement for the
standard library's :class:`pathlib.Path`, and provides the same
comprehensive set of operations.

For reading and writing to files and file-like objects, Trio also
provides a mechanism for wrapping any synchronous file-like object
into an asynchronous interface. If you have a :class:`trio.Path`
object you can get one of these by calling its :meth:`~trio.Path.open`
method; or if you know the file's name you can open it directly with
:func:`trio.open_file`. Alternatively, if you already have an open
file-like object, you can wrap it with :func:`trio.wrap_file` – one
case where this is especially useful is to wrap :class:`io.BytesIO` or
:class:`io.StringIO` when writing tests.


Asynchronous path objects
~~~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: Path
   :members:


Asynchronous file objects
~~~~~~~~~~~~~~~~~~~~~~~~~

.. autofunction:: open_file

.. autofunction:: wrap_file

.. interface:: Asynchronous file interface

   Trio's asynchronous file objects have an interface that
   automatically adapts to the object being wrapped. Intuitively, you
   can mostly treat them like a regular :term:`file object`, except
   adding an ``await`` in front of any of methods that do I/O. The
   definition of :term:`file object` is a little vague in Python
   though, so here are the details:

   * Synchronous attributes/methods: if any of the following
     attributes or methods are present, then they're re-exported
     unchanged: ``closed``, ``encoding``, ``errors``, ``fileno``,
     ``isatty``, ``newlines``, ``readable``, ``seekable``,
     ``writable``, ``buffer``, ``raw``, ``line_buffering``,
     ``closefd``, ``name``, ``mode``, ``getvalue``, ``getbuffer``.

   * Async methods: if any of the following methods are present, then
     they're re-exported as an async method: ``flush``, ``read``,
     ``read1``, ``readall``, ``readinto``, ``readline``,
     ``readlines``, ``seek``, ``tell`, ``truncate``, ``write``,
     ``writelines``, ``readinto1``, ``peek``, ``detach``.

   Special notes:

   * Async file objects implement trio's
     :class:`~trio.abc.AsyncResource` interface: you close them by
     calling :meth:`~trio.abc.AsyncResource.aclose` instead of
     ``close`` (!!), and they can be used as async context
     managers. Like all :meth:`~trio.abc.AsyncResource.aclose`
     methods, the ``aclose`` method on async file objects is
     guaranteed to close the file before returning, even if it is
     cancelled or otherwise raises an error.

   * Using the same async file object from multiple tasks
     simultaneously: because the async methods on async file objects
     are implemented using threads, it's only safe to call two of them
     at the same time from different tasks IF the underlying
     synchronous file object is thread-safe. You should consult the
     documentation for the object you're wrapping. For objects
     returned from :func:`trio.open_file` or `trio.Path.open`, it
     depends on whether you open the file in binary mode or text mode:
     `binary mode files are task-safe/thread-safe, text mode files are
     not
     <https://docs.python.org/3/library/io.html#multi-threading>`__.

   * Async file objects can be used as async iterators to iterate over
     the lines of the file::

        async with trio.open_file(...) as f:
            async for line in f:
                print(line)

   * The ``detach`` method, if present, returns an async file object.

   This should include all the attributes exposed by classes in
   :mod:`io`. But if you're wrapping an object that has other
   attributes that aren't on the list above, then you can access them
   via the ``.wrapped`` attribute:

   .. attribute:: wrapped

      The underlying synchronous file object.


Subprocesses
------------

`Not implemented yet! <https://github.com/python-trio/trio/issues/4>`__


Signals
-------

.. currentmodule:: trio

.. autofunction:: catch_signals
   :with: batched_signal_aiter
