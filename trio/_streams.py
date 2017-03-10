import abc
import contextlib

import attr

from . import _core

__all__ = ["AsyncResource", "SendStream", "RecvStream", "Stream"]

# The close API is a big question here.
#
# Technically, socket close can block if you set various weird
# lingering-related options. This doesn't seem very useful though.
#
# For other kinds of channels, though, the natural implementation definitely
# can block – e.g. TLS wants to send a goodbye message, and if we're tunneling
# over ssh or HTTP/2 e.g. then again closing requires sending some actual
# data. So we need a concept of a blocking close.
#
# BUT, if the other side is uncooperative, we can't necessarily block in
# close. So if a blocking close is cancelled, we need to do some sort of
# forceful cleanup before raising the exception.
#
# (Probably implementing H2-based streams will be a useful forcing function
# here to figure this out.)

class AsyncResource(metaclass=abc.ABCMeta):
    __slots__ = ()

    @abc.abstractmethod
    def forceful_close(self):
        """Force an immediate close of this resource.

        This will never block, but (depending on the resource in question) it
        might be a "rude" shutdown.
        """
        pass

    async def graceful_close(self):
        """Close this resource, gracefully.

        This may block in order to perform a "graceful" shutdown (for example,
        sending a message alerting the other side of a connection that it is
        about to close). But, if cancelled, then it still *must* close the
        underlying resource.

        Default implementation is to perform a :meth:`forceful_close` and then
        execute a yield point.
        """
        self.forceful_close()
        await _core.yield_briefly()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.graceful_close()

# XX added in 3.6
if hasattr(contextlib, "AbstractContextManager"):
    contextlib.AbstractContextManager.register(AsyncResource)

class SendStream(AsyncResource):
    __slots__ = ()

    @abc.abstractmethod
    async def sendall(self, data):
        pass

    # This is only a hint, because in some cases we don't know (Windows), or
    # we have only a noisy signal (TLS). And in the use cases this is included
    # to account for, returning before it's actually writable is NBD, it just
    # makes them slightly less efficient.
    @abc.abstractmethod
    async def wait_maybe_writable(self):
        pass

    @property
    @abc.abstractmethod
    def can_send_eof(self):
        pass

    @abc.abstractmethod
    def send_eof(self):
        pass

class RecvStream(AsyncResource):
    __slots__ = ()

    @abc.abstractmethod
    async def recv(self, max_bytes):
        pass

class Stream(SendStream, RecvStream):
    __slots__ = ()

    @staticmethod
    def staple(send_stream, recv_stream):
        return StapledStream(send_stream=send_stream, recv_stream=recv_stream)

@attr.s(slots=True, cmp=False, hash=False)
class StapledStream(Stream):
    send_stream = attr.ib()
    recv_stream = attr.ib()

    async def sendall(self, data):
        return await self.send_stream.sendall(data)

    async def wait_maybe_writable(self):
        return await self.send_stream.wait_maybe_writable()

    @property
    def can_send_eof(self):
        return self.send_stream.can_send_eof

    def send_eof(self):
        return self.send_stream.send_eof()

    async def recv(self, max_bytes):
        return self.recv_stream.recv(max_bytes)

    def forceful_close(self):
        try:
            self.send_stream.forceful_close()
        finally:
            self.recv_stream.forceful_close()

    async def graceful_close(self):
        try:
            await self.send_stream.graceful_close()
        finally:
            await self.recv_stream.graceful_close()
