# "High-level" networking interface
from __future__ import annotations

import errno
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, overload

import trio

from . import socket as tsocket
from ._util import ConflictDetector, final
from .abc import HalfCloseableStream, Listener

if TYPE_CHECKING:
    from collections.abc import Generator

    from ._socket import SocketType

import sys

if sys.version_info >= (3, 12):
    # NOTE: this isn't in the `TYPE_CHECKING` since for some reason
    # sphinx doesn't autoreload this module for SocketStream
    # (hypothesis: it's our module renaming magic)
    from collections.abc import Buffer
elif TYPE_CHECKING:
    from typing_extensions import Buffer

# XX TODO: this number was picked arbitrarily. We should do experiments to
# tune it. (Or make it dynamic -- one idea is to start small and increase it
# if we observe single reads filling up the whole buffer, at least within some
# limits.)
DEFAULT_RECEIVE_SIZE = 65536

_closed_stream_errnos = {
    # Unix
    errno.EBADF,
    # Windows
    errno.ENOTSOCK,
}


@contextmanager
def _translate_socket_errors_to_stream_errors() -> Generator[None, None, None]:
    try:
        yield
    except OSError as exc:
        if exc.errno in _closed_stream_errnos:
            raise trio.ClosedResourceError("this socket was already closed") from None
        else:
            raise trio.BrokenResourceError(f"socket connection broken: {exc}") from exc


@final
class SocketStream(HalfCloseableStream):
    """An implementation of the :class:`trio.abc.HalfCloseableStream`
    interface based on a raw network socket.

    Args:
      socket: The Trio socket object to wrap. Must have type ``SOCK_STREAM``,
          and be connected.

    By default for TCP sockets, :class:`SocketStream` enables ``TCP_NODELAY``,
    and (on platforms where it's supported) enables ``TCP_NOTSENT_LOWAT`` with
    a reasonable buffer size (currently 16 KiB) – see `issue #72
    <https://github.com/python-trio/trio/issues/72>`__ for discussion. You can
    of course override these defaults by calling :meth:`setsockopt`.

    Once a :class:`SocketStream` object is constructed, it implements the full
    :class:`trio.abc.HalfCloseableStream` interface. In addition, it provides
    a few extra features:

    .. attribute:: socket

       The Trio socket object that this stream wraps.

    """

    def __init__(self, socket: SocketType) -> None:
        if not isinstance(socket, tsocket.SocketType):
            raise TypeError("SocketStream requires a Trio socket object")
        if socket.type != tsocket.SOCK_STREAM:
            raise ValueError("SocketStream requires a SOCK_STREAM socket")

        self.socket = socket
        self._send_conflict_detector = ConflictDetector(
            "another task is currently sending data on this SocketStream",
        )

        # Socket defaults:

        # Not supported on e.g. unix domain sockets
        with suppress(OSError):
            self.setsockopt(tsocket.IPPROTO_TCP, tsocket.TCP_NODELAY, True)

        if hasattr(tsocket, "TCP_NOTSENT_LOWAT"):
            # 16 KiB is pretty arbitrary and could probably do with some
            # tuning. (Apple is also setting this by default in CFNetwork
            # apparently -- I'm curious what value they're using, though I
            # couldn't find it online trivially. CFNetwork-129.20 source
            # has no mentions of TCP_NOTSENT_LOWAT. This presentation says
            # "typically 8 kilobytes":
            # http://devstreaming.apple.com/videos/wwdc/2015/719ui2k57m/719/719_your_app_and_next_generation_networks.pdf?dl=1
            # ). The theory is that you want it to be bandwidth *
            # rescheduling interval.
            with suppress(OSError):
                self.setsockopt(tsocket.IPPROTO_TCP, tsocket.TCP_NOTSENT_LOWAT, 2**14)

    async def send_all(self, data: bytes | bytearray | memoryview) -> None:
        if self.socket.did_shutdown_SHUT_WR:
            raise trio.ClosedResourceError("can't send data after sending EOF")
        with self._send_conflict_detector:
            with _translate_socket_errors_to_stream_errors():
                with memoryview(data) as data:
                    if not data:
                        if self.socket.fileno() == -1:
                            raise trio.ClosedResourceError("socket was already closed")
                        await trio.lowlevel.checkpoint()
                        return
                    total_sent = 0
                    while total_sent < len(data):
                        with data[total_sent:] as remaining:
                            sent = await self.socket.send(remaining)
                        total_sent += sent

    async def wait_send_all_might_not_block(self) -> None:
        with self._send_conflict_detector:
            if self.socket.fileno() == -1:
                raise trio.ClosedResourceError
            with _translate_socket_errors_to_stream_errors():
                await self.socket.wait_writable()

    async def send_eof(self) -> None:
        with self._send_conflict_detector:
            await trio.lowlevel.checkpoint()
            # On macOS, calling shutdown a second time raises ENOTCONN, but
            # send_eof needs to be idempotent.
            if self.socket.did_shutdown_SHUT_WR:
                return
            with _translate_socket_errors_to_stream_errors():
                self.socket.shutdown(tsocket.SHUT_WR)

    async def receive_some(self, max_bytes: int | None = None) -> bytes:
        if max_bytes is None:
            max_bytes = DEFAULT_RECEIVE_SIZE
        if max_bytes < 1:
            raise ValueError("max_bytes must be >= 1")
        with _translate_socket_errors_to_stream_errors():
            return await self.socket.recv(max_bytes)

    async def aclose(self) -> None:
        self.socket.close()
        await trio.lowlevel.checkpoint()

    # __aenter__, __aexit__ inherited from HalfCloseableStream are OK

    @overload
    def setsockopt(self, level: int, option: int, value: int | Buffer) -> None: ...

    @overload
    def setsockopt(self, level: int, option: int, value: None, length: int) -> None: ...

    # TODO: rename `length` to `optlen`
    def setsockopt(
        self,
        level: int,
        option: int,
        value: int | Buffer | None,
        length: int | None = None,
    ) -> None:
        """Set an option on the underlying socket.

        See :meth:`socket.socket.setsockopt` for details.

        """
        if length is None:
            if value is None:
                raise TypeError(
                    "invalid value for argument 'value', must not be None when specifying length",
                )
            return self.socket.setsockopt(level, option, value)
        if value is not None:
            raise TypeError(
                f"invalid value for argument 'value': {value!r}, must be None when specifying optlen",
            )
        return self.socket.setsockopt(level, option, value, length)

    @overload
    def getsockopt(self, level: int, option: int) -> int: ...

    @overload
    def getsockopt(self, level: int, option: int, buffersize: int) -> bytes: ...

    def getsockopt(self, level: int, option: int, buffersize: int = 0) -> int | bytes:
        """Check the current value of an option on the underlying socket.

        See :meth:`socket.socket.getsockopt` for details.

        """
        # This is to work around
        #   https://bitbucket.org/pypy/pypy/issues/2561
        # We should be able to drop it when the next PyPy3 beta is released.
        if buffersize == 0:
            return self.socket.getsockopt(level, option)
        else:
            return self.socket.getsockopt(level, option, buffersize)


################################################################
# SocketListener
################################################################

# Accept error handling
# =====================
#
# Literature review
# -----------------
#
# Here's a list of all the possible errors that accept() can return, according
# to the POSIX spec or the Linux, FreeBSD, macOS, and Windows docs:
#
# Can't happen with a Trio socket:
# - EAGAIN/(WSA)EWOULDBLOCK
# - EINTR
# - WSANOTINITIALISED
# - WSAEINPROGRESS: a blocking call is already in progress
# - WSAEINTR: someone called WSACancelBlockingCall, but we don't make blocking
#   calls in the first place
#
# Something is wrong with our call:
# - EBADF: not a file descriptor
# - (WSA)EINVAL: socket isn't listening, or (Linux, BSD) bad flags
# - (WSA)ENOTSOCK: not a socket
# - (WSA)EOPNOTSUPP: this kind of socket doesn't support accept
# - (Linux, FreeBSD, Windows) EFAULT: the sockaddr pointer points to readonly
#   memory
#
# Something is wrong with the environment:
# - (WSA)EMFILE: this process hit its fd limit
# - ENFILE: the system hit its fd limit
# - (WSA)ENOBUFS, ENOMEM: unspecified memory problems
#
# Something is wrong with the connection we were going to accept. There's a
# ton of variability between systems here:
# - ECONNABORTED: documented everywhere, but apparently only the BSDs do this
#   (signals a connection was closed/reset before being accepted)
# - EPROTO: unspecified protocol error
# - (Linux) EPERM: firewall rule prevented connection
# - (Linux) ENETDOWN, EPROTO, ENOPROTOOPT, EHOSTDOWN, ENONET, EHOSTUNREACH,
#   EOPNOTSUPP, ENETUNREACH, ENOSR, ESOCKTNOSUPPORT, EPROTONOSUPPORT,
#   ETIMEDOUT, ... or any other error that the socket could give, because
#   apparently if an error happens on a connection before it's accept()ed,
#   Linux will report that error from accept().
# - (Windows) WSAECONNRESET, WSAENETDOWN
#
#
# Code review
# -----------
#
# What do other libraries do?
#
# Twisted on Unix or when using nonblocking I/O on Windows:
# - ignores EPERM, with comment about Linux firewalls
# - logs and ignores EMFILE, ENOBUFS, ENFILE, ENOMEM, ECONNABORTED
#   Comment notes that ECONNABORTED is a BSDism and that Linux returns the
#   socket before having it fail, and macOS just silently discards it.
# - other errors are raised, which is logged + kills the socket
# ref: src/twisted/internet/tcp.py, Port.doRead
#
# Twisted using IOCP on Windows:
# - logs and ignores all errors
# ref: src/twisted/internet/iocpreactor/tcp.py, Port.handleAccept
#
# Tornado:
# - ignore ECONNABORTED (comments notes that it was observed on FreeBSD)
# - everything else raised, but all this does (by default) is cause it to be
#   logged and then ignored
# (ref: tornado/netutil.py, tornado/ioloop.py)
#
# libuv on Unix:
# - ignores ECONNABORTED
# - does a "trick" for EMFILE or ENFILE
# - all other errors passed to the connection_cb to be handled
# (ref: src/unix/stream.c:uv__server_io, uv__emfile_trick)
#
# libuv on Windows:
# src/win/tcp.c:uv_tcp_queue_accept
#   this calls AcceptEx, and then arranges to call:
# src/win/tcp.c:uv_process_tcp_accept_req
#   this gets the result from AcceptEx. If the original AcceptEx call failed,
#   then "we stop accepting connections and report this error to the
#   connection callback". I think this is for things like ENOTSOCK. If
#   AcceptEx successfully queues an overlapped operation, and then that
#   reports an error, it's just discarded.
#
# asyncio, selector mode:
# - ignores EWOULDBLOCK, EINTR, ECONNABORTED
# - on EMFILE, ENFILE, ENOBUFS, ENOMEM, logs an error and then disables the
#   listening loop for 1 second
# - everything else raises, but then the event loop just logs and ignores it
# (selector_events.py: BaseSelectorEventLoop._accept_connection)
#
#
# What should we do?
# ------------------
#
# When accept() returns an error, we can either ignore it or raise it.
#
# We have a long list of errors that should be ignored, and a long list of
# errors that should be raised. The big question is what to do with an error
# that isn't on either list. On Linux apparently you can get nearly arbitrary
# errors from accept() and they should be ignored, because it just indicates a
# socket that crashed before it began, and there isn't really anything to be
# done about this, plus on other platforms you may not get any indication at
# all, so programs have to tolerate not getting any indication too. OTOH if we
# get an unexpected error then it could indicate something arbitrarily bad --
# after all, it's unexpected.
#
# Given that we know that other libraries seem to be getting along fine with a
# fairly minimal list of errors to ignore, I think we'll be OK if we write
# down that list and then raise on everything else.
#
# The other question is what to do about the capacity problem errors: EMFILE,
# ENFILE, ENOBUFS, ENOMEM. Just flat out ignoring these is clearly not optimal
# -- at the very least you want to log them, and probably you want to take
# some remedial action. And if we ignore them then it prevents higher levels
# from doing anything clever with them. So we raise them.

_ignorable_accept_errno_names = [
    # Linux can do this when the a connection is denied by the firewall
    "EPERM",
    # BSDs with an early close/reset
    "ECONNABORTED",
    # All the other miscellany noted above -- may not happen in practice, but
    # whatever.
    "EPROTO",
    "ENETDOWN",
    "ENOPROTOOPT",
    "EHOSTDOWN",
    "ENONET",
    "EHOSTUNREACH",
    "EOPNOTSUPP",
    "ENETUNREACH",
    "ENOSR",
    "ESOCKTNOSUPPORT",
    "EPROTONOSUPPORT",
    "ETIMEDOUT",
    "ECONNRESET",
]

# Not all errnos are defined on all platforms
_ignorable_accept_errnos: set[int] = set()
for name in _ignorable_accept_errno_names:
    with suppress(AttributeError):
        _ignorable_accept_errnos.add(getattr(errno, name))


@final
class SocketListener(Listener[SocketStream]):
    """A :class:`~trio.abc.Listener` that uses a listening socket to accept
    incoming connections as :class:`SocketStream` objects.

    Args:
      socket: The Trio socket object to wrap. Must have type ``SOCK_STREAM``,
          and be listening.

    Note that the :class:`SocketListener` "takes ownership" of the given
    socket; closing the :class:`SocketListener` will also close the socket.

    .. attribute:: socket

       The Trio socket object that this stream wraps.

    """

    def __init__(self, socket: SocketType) -> None:
        if not isinstance(socket, tsocket.SocketType):
            raise TypeError("SocketListener requires a Trio socket object")
        if socket.type != tsocket.SOCK_STREAM:
            raise ValueError("SocketListener requires a SOCK_STREAM socket")
        try:
            listening = socket.getsockopt(tsocket.SOL_SOCKET, tsocket.SO_ACCEPTCONN)
        except OSError:
            # SO_ACCEPTCONN fails on macOS; we just have to trust the user.
            pass
        else:
            if not listening:
                raise ValueError("SocketListener requires a listening socket")

        self.socket = socket

    async def accept(self) -> SocketStream:
        """Accept an incoming connection.

        Returns:
          :class:`SocketStream`

        Raises:
          OSError: if the underlying call to ``accept`` raises an unexpected
              error.
          ClosedResourceError: if you already closed the socket.

        This method handles routine errors like ``ECONNABORTED``, but passes
        other errors on to its caller. In particular, it does *not* make any
        special effort to handle resource exhaustion errors like ``EMFILE``,
        ``ENFILE``, ``ENOBUFS``, ``ENOMEM``.

        """
        while True:
            try:
                sock, _ = await self.socket.accept()
            except OSError as exc:
                if exc.errno in _closed_stream_errnos:
                    raise trio.ClosedResourceError from None
                if exc.errno not in _ignorable_accept_errnos:
                    raise
            else:
                return SocketStream(sock)

    async def aclose(self) -> None:
        """Close this listener and its underlying socket."""
        self.socket.close()
        await trio.lowlevel.checkpoint()
