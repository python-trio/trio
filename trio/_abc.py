from abc import ABCMeta, abstractmethod
from . import _core

__all__ = [
    "Clock",
    "Instrument",
    "AsyncResource",
    "SendStream",
    "ReceiveStream",
    "Stream",
    "HalfCloseableStream",
    "SocketFactory",
    "HostnameResolver",
    "Listener",
]


# We use ABCMeta instead of ABC, plus set __slots__=(), so as not to force a
# __dict__ onto subclasses.
class Clock(metaclass=ABCMeta):
    """The interface for custom run loop clocks.

    """
    __slots__ = ()

    @abstractmethod
    def start_clock(self):
        """Do any setup this clock might need.

        Called at the beginning of the run.

        """

    @abstractmethod
    def current_time(self):
        """Return the current time, according to this clock.

        This is used to implement functions like :func:`trio.current_time` and
        :func:`trio.move_on_after`.

        Returns:
            float: The current time.

        """

    @abstractmethod
    def deadline_to_sleep_time(self, deadline):
        """Compute the real time until the given deadline.

        This is called before we enter a system-specific wait function like
        :func:`select.select`, to get the timeout to pass.

        For a clock using wall-time, this should be something like::

           return deadline - self.current_time()

        but of course it may be different if you're implementing some kind of
        virtual clock.

        Args:
            deadline (float): The absolute time of the next deadline,
                according to this clock.

        Returns:
            float: The number of real seconds to sleep until the given
            deadline. May be :data:`math.inf`.

        """


class Instrument(metaclass=ABCMeta):
    """The interface for run loop instrumentation.

    Instruments don't have to inherit from this abstract base class, and all
    of these methods are optional. This class serves mostly as documentation.

    """
    __slots__ = ()

    def before_run(self):
        """Called at the beginning of :func:`trio.run`.

        """

    def after_run(self):
        """Called just before :func:`trio.run` returns.

        """

    def task_spawned(self, task):
        """Called when the given task is created.

        Args:
            task (trio.hazmat.Task): The new task.

        """

    def task_scheduled(self, task):
        """Called when the given task becomes runnable.

        It may still be some time before it actually runs, if there are other
        runnable tasks ahead of it.

        Args:
            task (trio.hazmat.Task): The task that became runnable.

        """

    def before_task_step(self, task):
        """Called immediately before we resume running the given task.

        Args:
            task (trio.hazmat.Task): The task that is about to run.

        """

    def after_task_step(self, task):
        """Called when we return to the main run loop after a task has yielded.

        Args:
            task (trio.hazmat.Task): The task that just ran.

        """

    def task_exited(self, task):
        """Called when the given task exits.

        Args:
            task (trio.hazmat.Task): The finished task.

        """

    def before_io_wait(self, timeout):
        """Called before blocking to wait for I/O readiness.

        Args:
            timeout (float): The number of seconds we are willing to wait.

        """

    def after_io_wait(self, timeout):
        """Called after handling pending I/O.

        Args:
            timeout (float): The number of seconds we were willing to
                wait. This much time may or may not have elapsed, depending on
                whether any I/O was ready.

        """


class HostnameResolver(metaclass=ABCMeta):
    """If you have a custom hostname resolver, then implementing
    :class:`HostnameResolver` allows you to register this to be used by trio.

    See :func:`trio.socket.set_custom_hostname_resolver`.

    """
    __slots__ = ()

    @abstractmethod
    async def getaddrinfo(
        self, host, port, family=0, type=0, proto=0, flags=0
    ):
        """A custom implementation of :func:`~trio.socket.getaddrinfo`.

        Called by :func:`trio.socket.getaddrinfo`.

        If ``host`` is given as a numeric IP address, then
        :func:`~trio.socket.getaddrinfo` may handle the request itself rather
        than calling this method.

        Any required IDNA encoding is handled before calling this function;
        your implementation can assume that it will never see U-labels like
        ``"café.com"``, and only needs to handle A-labels like
        ``b"xn--caf-dma.com"``.

        """

    @abstractmethod
    async def getnameinfo(self, sockaddr, flags):
        """A custom implementation of :func:`~trio.socket.getnameinfo`.

        Called by :func:`trio.socket.getnameinfo`.

        """


class SocketFactory(metaclass=ABCMeta):
    """If you write a custom class implementing the trio socket interface,
    then you can use a :class:`SocketFactory` to get trio to use it.

    See :func:`trio.socket.set_custom_socket_factory`.

    """

    @abstractmethod
    def socket(self, family=None, type=None, proto=None):
        """Create and return a socket object.

        Your socket object must inherit from :class:`trio.socket.SocketType`,
        which is an empty class whose only purpose is to "mark" which classes
        should be considered valid trio sockets.

        Called by :func:`trio.socket.socket`.

        Note that unlike :func:`trio.socket.socket`, this does not take a
        ``fileno=`` argument. If a ``fileno=`` is specified, then
        :func:`trio.socket.socket` returns a regular trio socket object
        instead of calling this method.

        """


class AsyncResource(metaclass=ABCMeta):
    """A standard interface for resources that needs to be cleaned up, and
    where that cleanup may require blocking operations.

    This class distinguishes between "graceful" closes, which may perform I/O
    and thus block, and a "forceful" close, which cannot. For example, cleanly
    shutting down a TLS-encrypted connection requires sending a "goodbye"
    message; but if a peer has become non-responsive, then sending this
    message might block forever, so we may want to just drop the connection
    instead. Therefore the :meth:`aclose` method is unusual in that it
    should always close the connection (or at least make its best attempt)
    *even if it fails*; failure indicates a failure to achieve grace, not a
    failure to close the connection.

    Objects that implement this interface can be used as async context
    managers, i.e., you can write::

      async with create_resource() as some_async_resource:
          ...

    Entering the context manager is synchronous (not a checkpoint); exiting it
    calls :meth:`aclose`. The default implementations of
    ``__aenter__`` and ``__aexit__`` should be adequate for all subclasses.

    """
    __slots__ = ()

    @abstractmethod
    async def aclose(self):
        """Close this resource, possibly blocking.

        IMPORTANT: This method may block in order to perform a "graceful"
        shutdown. But, if this fails, then it still *must* close any
        underlying resources before returning. An error from this method
        indicates a failure to achieve grace, *not* a failure to close the
        connection.

        For example, suppose we call :meth:`aclose` on a TLS-encrypted
        connection. This requires sending a "goodbye" message; but if the peer
        has become non-responsive, then our attempt to send this message might
        block forever, and eventually time out and be cancelled. In this case
        the :meth:`aclose` method on :class:`~trio.ssl.SSLStream` will
        immediately close the underlying transport stream using
        :func:`trio.aclose_forcefully` before raising :exc:`~trio.Cancelled`.

        If the resource is already closed, then this method should silently
        succeed.

        See also: :func:`trio.aclose_forcefully`.

        """

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()


class SendStream(AsyncResource):
    """A standard interface for sending data on a byte stream.

    The underlying stream may be unidirectional, or bidirectional. If it's
    bidirectional, then you probably want to also implement
    :class:`ReceiveStream`, which makes your object a :class:`Stream`.

    Every :class:`SendStream` also implements the :class:`AsyncResource`
    interface.

    """
    __slots__ = ()

    @abstractmethod
    async def send_all(self, data):
        """Sends the given data through the stream, blocking if necessary.

        Args:
          data (bytes, bytearray, or memoryview): The data to send.

        Raises:
          trio.ResourceBusyError: if another task is already executing a
              :meth:`send_all`, :meth:`wait_send_all_might_not_block`, or
              :meth:`HalfCloseableStream.send_eof` on this stream.
          trio.BrokenStreamError: if something has gone wrong, and the stream
              is broken.
          trio.ClosedStreamError: if you already closed this stream object.

        Most low-level operations in trio provide a guarantee: if they raise
        :exc:`trio.Cancelled`, this means that they had no effect, so the
        system remains in a known state. This is **not true** for
        :meth:`send_all`. If this operation raises :exc:`trio.Cancelled` (or
        any other exception for that matter), then it may have sent some, all,
        or none of the requested data, and there is no way to know which.

        """

    @abstractmethod
    async def wait_send_all_might_not_block(self):
        """Block until it's possible that :meth:`send_all` might not block.

        This method may return early: it's possible that after it returns,
        :meth:`send_all` will still block. (In the worst case, if no better
        implementation is available, then it might always return immediately
        without blocking. It's nice to do better than that when possible,
        though.)

        This method **must not** return *late*: if it's possible for
        :meth:`send_all` to complete without blocking, then it must
        return. When implementing it, err on the side of returning early.

        Raises:
          trio.ResourceBusyError: if another task is already executing a
              :meth:`send_all`, :meth:`wait_send_all_might_not_block`, or
              :meth:`HalfCloseableStream.send_eof` on this stream.
          trio.BrokenStreamError: if something has gone wrong, and the stream
              is broken.
          trio.ClosedStreamError: if you already closed this stream object.

        Note:

          This method is intended to aid in implementing protocols that want
          to delay choosing which data to send until the last moment. E.g.,
          suppose you're working on an implemention of a remote display server
          like `VNC
          <https://en.wikipedia.org/wiki/Virtual_Network_Computing>`__, and
          the network connection is currently backed up so that if you call
          :meth:`send_all` now then it will sit for 0.5 seconds before actually
          sending anything. In this case it doesn't make sense to take a
          screenshot, then wait 0.5 seconds, and then send it, because the
          screen will keep changing while you wait; it's better to wait 0.5
          seconds, then take the screenshot, and then send it, because this
          way the data you deliver will be more
          up-to-date. Using :meth:`wait_send_all_might_not_block` makes it
          possible to implement the better strategy.

          If you use this method, you might also want to read up on
          ``TCP_NOTSENT_LOWAT``.

          Further reading:

          * `Prioritization Only Works When There's Pending Data to Prioritize
            <https://insouciant.org/tech/prioritization-only-works-when-theres-pending-data-to-prioritize/>`__

          * WWDC 2015: Your App and Next Generation Networks: `slides
            <http://devstreaming.apple.com/videos/wwdc/2015/719ui2k57m/719/719_your_app_and_next_generation_networks.pdf?dl=1>`__,
            `video and transcript
            <https://developer.apple.com/videos/play/wwdc2015/719/>`__

        """


class ReceiveStream(AsyncResource):
    """A standard interface for receiving data on a byte stream.

    The underlying stream may be unidirectional, or bidirectional. If it's
    bidirectional, then you probably want to also implement
    :class:`SendStream`, which makes your object a :class:`Stream`.

    Every :class:`ReceiveStream` also implements the :class:`AsyncResource`
    interface.

    """
    __slots__ = ()

    @abstractmethod
    async def receive_some(self, max_bytes):
        """Wait until there is data available on this stream, and then return
        at most ``max_bytes`` of it.

        A return value of ``b""`` (an empty bytestring) indicates that the
        stream has reached end-of-file. Implementations should be careful that
        they return ``b""`` if, and only if, the stream has reached
        end-of-file!

        This method will return as soon as any data is available, so it may
        return fewer than ``max_bytes`` of data. But it will never return
        more.

        Args:
          max_bytes (int): The maximum number of bytes to return. Must be
              greater than zero.

        Returns:
          bytes or bytearray: The data received.

        Raises:
          trio.ResourceBusyError: if two tasks attempt to call
              :meth:`receive_some` on the same stream at the same time.
          trio.BrokenStreamError: if something has gone wrong, and the stream
              is broken.
          trio.ClosedStreamError: if you already closed this stream object.

        """


class Stream(SendStream, ReceiveStream):
    """A standard interface for interacting with bidirectional byte streams.

    A :class:`Stream` is an object that implements both the
    :class:`SendStream` and :class:`ReceiveStream` interfaces.

    If implementing this interface, you should consider whether you can go one
    step further and implement :class:`HalfCloseableStream`.

    """
    __slots__ = ()


class HalfCloseableStream(Stream):
    """This interface extends :class:`Stream` to also allow closing the send
    part of the stream without closing the receive part.

    """
    __slots__ = ()

    @abstractmethod
    async def send_eof(self):
        """Send an end-of-file indication on this stream, if possible.

        The difference between :meth:`send_eof` and
        :meth:`~AsyncResource.aclose` is that :meth:`send_eof` is a
        *unidirectional* end-of-file indication. After you call this method,
        you shouldn't try sending any more data on this stream, and your
        remote peer should receive an end-of-file indication (eventually,
        after receiving all the data you sent before that). But, they may
        continue to send data to you, and you can continue to receive it by
        calling :meth:`~ReceiveStream.receive_some`. You can think of it as
        calling :meth:`~AsyncResource.aclose` on just the
        :class:`SendStream` "half" of the stream object (and in fact that's
        literally how :class:`trio.StapledStream` implements it).

        Examples:

        * On a socket, this corresponds to ``shutdown(..., SHUT_WR)`` (`man
          page <https://linux.die.net/man/2/shutdown>`__).

        * The SSH protocol provides the ability to multiplex bidirectional
          "channels" on top of a single encrypted connection. A trio
          implementation of SSH could expose these channels as
          :class:`HalfCloseableStream` objects, and calling :meth:`send_eof`
          would send an ``SSH_MSG_CHANNEL_EOF`` request (see `RFC 4254 §5.3
          <https://tools.ietf.org/html/rfc4254#section-5.3>`__).

        * On an SSL/TLS-encrypted connection, the protocol doesn't provide any
          way to do a unidirectional shutdown without closing the connection
          entirely, so :class:`~trio.ssl.SSLStream` implements
          :class:`Stream`, not :class:`HalfCloseableStream`.

        If an EOF has already been sent, then this method should silently
        succeed.

        Raises:
          trio.ResourceBusyError: if another task is already executing a
              :meth:`~SendStream.send_all`,
              :meth:`~SendStream.wait_send_all_might_not_block`, or
              :meth:`send_eof` on this stream.
          trio.BrokenStreamError: if something has gone wrong, and the stream
              is broken.
          trio.ClosedStreamError: if you already closed this stream object.

        """


class Listener(AsyncResource):
    """A standard interface for listening for incoming connections.

    """
    __slots__ = ()

    @abstractmethod
    async def accept(self):
        """Wait until an incoming connection arrives, and then return it.

        Returns:
          AsyncResource: An object representing the incoming connection. In
          practice this is almost always some variety of :class:`Stream`,
          though in principle you could also use this interface with, say,
          SOCK_SEQPACKET sockets or similar.

        Raises:
          trio.ResourceBusyError: if two tasks attempt to call
              :meth:`accept` on the same listener at the same time.
          trio.ClosedListenerError: if you already closed this listener.

        Note that there is no ``BrokenListenerError``, because for listeners
        there is no general condition of "the network/remote peer broke the
        connection" that can be handled in a generic way, like there is for
        streams. Other errors *can* occur and be raised from :meth:`accept` –
        for example, if you run out of file descriptors then you might get an
        :class:`OSError` with its errno set to ``EMFILE``.

        """
