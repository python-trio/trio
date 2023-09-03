import errno
import socket as stdlib_socket
import sys
from math import inf

import attr
import pytest

import trio
from trio import UnixSocketListener, open_tcp_stream, open_unix_listeners, serve_unix
from trio.testing import open_stream_to_socket_listener

from .. import _core, socket as tsocket
from .._core._tests.tutil import binds_ipv6
from .._highlevel_socket import *
from ..testing import assert_checkpoints

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup


async def test_UnixSocketListener() -> None:
    # Not a Trio socket
    with stdlib_socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(10)
        with pytest.raises(TypeError):
            UnixSocketListener(s)

    # Not a SOCK_STREAM
    with tsocket.socket(type=tsocket.SOCK_DGRAM) as s:
        await s.bind(("127.0.0.1", 0))
        with pytest.raises(ValueError) as excinfo:
            UnixSocketListener(s)
        excinfo.match(r".*SOCK_STREAM")

    # Didn't call .listen()
    # macOS has no way to check for this, so skip testing it there.
    if sys.platform != "darwin":
        with tsocket.socket() as s:
            await s.bind(("127.0.0.1", 0))
            with pytest.raises(ValueError) as excinfo:
                UnixSocketListener(s)
            excinfo.match(r".*listen")

    listen_sock = tsocket.socket()
    await listen_sock.bind(("127.0.0.1", 0))
    listen_sock.listen(10)
    listener = UnixSocketListener(listen_sock)

    assert listener.socket is listen_sock

    client_sock = tsocket.socket()
    await client_sock.connect(listen_sock.getsockname())
    with assert_checkpoints():
        server_stream = await listener.accept()
    assert isinstance(server_stream, SocketStream)
    assert server_stream.socket.getsockname() == listen_sock.getsockname()
    assert server_stream.socket.getpeername() == client_sock.getsockname()

    with assert_checkpoints():
        await listener.aclose()

    with assert_checkpoints():
        await listener.aclose()

    with assert_checkpoints():
        with pytest.raises(_core.ClosedResourceError):
            await listener.accept()

    client_sock.close()
    await server_stream.aclose()


async def test_UnixSocketListener_socket_closed_underfoot() -> None:
    listen_sock = tsocket.socket()
    await listen_sock.bind(("127.0.0.1", 0))
    listen_sock.listen(10)
    listener = UnixSocketListener(listen_sock)

    # Close the socket, not the listener
    listen_sock.close()

    # UnixSocketListener gives correct error
    with assert_checkpoints():
        with pytest.raises(_core.ClosedResourceError):
            await listener.accept()


async def test_UnixSocketListener_accept_errors() -> None:
    class FakeSocket(tsocket.SocketType):
        def __init__(self, events) -> None:
            self._events = iter(events)

        type = tsocket.SOCK_STREAM

        # Fool the check for SO_ACCEPTCONN in UnixSocketListener.__init__
        def getsockopt(self, level: object, opt: object) -> bool:
            return True

        def setsockopt(self, level: object, opt: object, value: object) -> None:
            pass

        async def accept(self):
            await _core.checkpoint()
            event = next(self._events)
            if isinstance(event, BaseException):
                raise event
            else:
                return event, None

    fake_server_sock = FakeSocket([])

    fake_listen_sock = FakeSocket(
        [
            OSError(errno.ECONNABORTED, "Connection aborted"),
            OSError(errno.EPERM, "Permission denied"),
            OSError(errno.EPROTO, "Bad protocol"),
            fake_server_sock,
            OSError(errno.EMFILE, "Out of file descriptors"),
            OSError(errno.EFAULT, "attempt to write to read-only memory"),
            OSError(errno.ENOBUFS, "out of buffers"),
            fake_server_sock,
        ]
    )

    l = UnixSocketListener(fake_listen_sock)

    with assert_checkpoints():
        s = await l.accept()
        assert s.socket is fake_server_sock

    for code in [errno.EMFILE, errno.EFAULT, errno.ENOBUFS]:
        with assert_checkpoints():
            with pytest.raises(OSError) as excinfo:
                await l.accept()
            assert excinfo.value.errno == code

    with assert_checkpoints():
        s = await l.accept()
        assert s.socket is fake_server_sock


async def test_socket_stream_works_when_peer_has_already_closed() -> None:
    sock_a, sock_b = tsocket.socketpair()
    with sock_a, sock_b:
        await sock_b.send(b"x")
        sock_b.close()
        stream = SocketStream(sock_a)
        assert await stream.receive_some(1) == b"x"
        assert await stream.receive_some(1) == b""


async def test_open_unix_listeners_basic() -> None:
    listeners = await open_unix_listeners(0)
    assert isinstance(listeners, list)
    for obj in listeners:
        assert isinstance(obj, UnixSocketListener)
        # Binds to wildcard address by default
        assert obj.socket.family in [tsocket.AF_INET, tsocket.AF_INET6]
        assert obj.socket.getsockname()[0] in ["0.0.0.0", "::"]

    listener = listeners[0]
    # Make sure the backlog is at least 2
    c1 = await open_stream_to_socket_listener(listener)
    c2 = await open_stream_to_socket_listener(listener)

    s1 = await listener.accept()
    s2 = await listener.accept()

    # Note that we don't know which client stream is connected to which server
    # stream
    await s1.send_all(b"x")
    await s2.send_all(b"x")
    assert await c1.receive_some(1) == b"x"
    assert await c2.receive_some(1) == b"x"

    for resource in [c1, c2, s1, s2] + listeners:
        await resource.aclose()


async def test_open_unix_listeners_specific_port_specific_host() -> None:
    # Pick a port
    sock = tsocket.socket()
    await sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    sock.close()

    (listener,) = await open_unix_listeners(port, host=host)
    async with listener:
        assert listener.socket.getsockname() == (host, port)


@binds_ipv6
async def test_open_unix_listeners_ipv6_v6only() -> None:
    # Check IPV6_V6ONLY is working properly
    (ipv6_listener,) = await open_unix_listeners(0, host="::1")
    async with ipv6_listener:
        _, port, *_ = ipv6_listener.socket.getsockname()

        with pytest.raises(OSError):
            await open_tcp_stream("127.0.0.1", port)


async def test_open_unix_listeners_rebind() -> None:
    (l1,) = await open_unix_listeners(0, host="127.0.0.1")
    sockaddr1 = l1.socket.getsockname()

    # Plain old rebinding while it's still there should fail, even if we have
    # SO_REUSEADDR set
    with stdlib_socket.socket() as probe:
        probe.setsockopt(stdlib_socket.SOL_SOCKET, stdlib_socket.SO_REUSEADDR, 1)
        with pytest.raises(OSError):
            probe.bind(sockaddr1)

    # Now use the first listener to set up some connections in various states,
    # and make sure that they don't create any obstacle to rebinding a second
    # listener after the first one is closed.
    c_established = await open_stream_to_socket_listener(l1)
    s_established = await l1.accept()

    c_time_wait = await open_stream_to_socket_listener(l1)
    s_time_wait = await l1.accept()
    # Server-initiated close leaves socket in TIME_WAIT
    await s_time_wait.aclose()

    await l1.aclose()
    (l2,) = await open_unix_listeners(sockaddr1[1], host="127.0.0.1")
    sockaddr2 = l2.socket.getsockname()

    assert sockaddr1 == sockaddr2
    assert s_established.socket.getsockname() == sockaddr2
    assert c_time_wait.socket.getpeername() == sockaddr2

    for resource in [
        l1,
        l2,
        c_established,
        s_established,
        c_time_wait,
        s_time_wait,
    ]:
        await resource.aclose()


class FakeOSError(OSError):
    __slots__ = ()


@attr.s
class FakeSocket(tsocket.SocketType):
    family = attr.ib()
    type = attr.ib()
    proto = attr.ib()

    closed = attr.ib(default=False)
    poison_listen = attr.ib(default=False)
    backlog = attr.ib(default=None)

    def getsockopt(self, level: int, option: int) -> bool:
        if (level, option) == (tsocket.SOL_SOCKET, tsocket.SO_ACCEPTCONN):
            return True
        assert False  # pragma: no cover

    def setsockopt(self, level: object, option: object, value: object) -> None:
        pass

    async def bind(self, sockaddr: object) -> None:
        pass

    def listen(self, backlog: int) -> None:
        assert self.backlog is None
        assert backlog is not None
        self.backlog = backlog
        if self.poison_listen:
            raise FakeOSError("whoops")

    def close(self) -> None:
        self.closed = True


@attr.s
class FakeSocketFactory:
    poison_after: int = attr.ib()
    sockets: list[FakeSocket] = attr.ib(factory=list)
    raise_on_family: dict[int, int] = attr.ib(factory=dict)  # family => errno

    def socket(self, family: int, type: int, proto: int) -> FakeSocket:
        if family in self.raise_on_family:
            raise OSError(self.raise_on_family[family], "nope")
        sock = FakeSocket(family, type, proto)
        self.poison_after -= 1
        if self.poison_after == 0:
            sock.poison_listen = True
        self.sockets.append(sock)
        return sock


@attr.s
class FakeHostnameResolver:
    family_addr_pairs = attr.ib()

    async def getaddrinfo(
        self,
        host: str | bytes,
        port: int,
        family: int,
        type: int,
        proto: int,
        flags: int,
    ) -> list[tuple[int, int, int, str, tuple[str | bytes, int]]]:
        return [
            (family, tsocket.SOCK_STREAM, 0, "", (addr, port))
            for family, addr in self.family_addr_pairs
        ]


async def test_open_unix_listeners_multiple_host_cleanup_on_error() -> None:
    # If we were trying to bind to multiple hosts and one of them failed, they
    # call get cleaned up before returning
    fsf = FakeSocketFactory(3)
    tsocket.set_custom_socket_factory(fsf)
    tsocket.set_custom_hostname_resolver(
        FakeHostnameResolver(
            [
                (tsocket.AF_INET, "1.1.1.1"),
                (tsocket.AF_INET, "2.2.2.2"),
                (tsocket.AF_INET, "3.3.3.3"),
            ]
        )
    )

    with pytest.raises(FakeOSError):
        await open_unix_listeners(80, host="example.org")

    assert len(fsf.sockets) == 3
    for sock in fsf.sockets:
        assert sock.closed


async def test_open_unix_listeners_port_checking() -> None:
    for host in ["127.0.0.1", None]:
        with pytest.raises(TypeError):
            await open_unix_listeners(None, host=host)
        with pytest.raises(TypeError):
            await open_unix_listeners(b"80", host=host)
        with pytest.raises(TypeError):
            await open_unix_listeners("http", host=host)


async def test_serve_tcp() -> None:
    async def handler(stream) -> None:
        await stream.send_all(b"x")

    async with trio.open_nursery() as nursery:
        listeners = await nursery.start(serve_unix, handler, 0)
        stream = await open_stream_to_socket_listener(listeners[0])
        async with stream:
            await stream.receive_some(1) == b"x"
            nursery.cancel_scope.cancel()


@pytest.mark.parametrize(
    "try_families",
    [{tsocket.AF_INET}, {tsocket.AF_INET6}, {tsocket.AF_INET, tsocket.AF_INET6}],
)
@pytest.mark.parametrize(
    "fail_families",
    [{tsocket.AF_INET}, {tsocket.AF_INET6}, {tsocket.AF_INET, tsocket.AF_INET6}],
)
async def test_open_unix_listeners_some_address_families_unavailable(
    try_families, fail_families
):
    fsf = FakeSocketFactory(
        10, raise_on_family={family: errno.EAFNOSUPPORT for family in fail_families}
    )
    tsocket.set_custom_socket_factory(fsf)
    tsocket.set_custom_hostname_resolver(
        FakeHostnameResolver([(family, "foo") for family in try_families])
    )

    should_succeed = try_families - fail_families

    if not should_succeed:
        with pytest.raises(OSError) as exc_info:
            await open_unix_listeners(80, host="example.org")

        assert "This system doesn't support" in str(exc_info.value)
        if isinstance(exc_info.value.__cause__, BaseExceptionGroup):
            for subexc in exc_info.value.__cause__.exceptions:
                assert "nope" in str(subexc)
        else:
            assert isinstance(exc_info.value.__cause__, OSError)
            assert "nope" in str(exc_info.value.__cause__)
    else:
        listeners = await open_unix_listeners(80)
        for listener in listeners:
            should_succeed.remove(listener.socket.family)
        assert not should_succeed


async def test_open_unix_listeners_socket_fails_not_afnosupport() -> None:
    fsf = FakeSocketFactory(
        10,
        raise_on_family={
            tsocket.AF_INET: errno.EAFNOSUPPORT,
            tsocket.AF_INET6: errno.EINVAL,
        },
    )
    tsocket.set_custom_socket_factory(fsf)
    tsocket.set_custom_hostname_resolver(
        FakeHostnameResolver([(tsocket.AF_INET, "foo"), (tsocket.AF_INET6, "bar")])
    )

    with pytest.raises(OSError) as exc_info:
        await open_unix_listeners(80, host="example.org")
    assert exc_info.value.errno == errno.EINVAL
    assert exc_info.value.__cause__ is None
    assert "nope" in str(exc_info.value)


# We used to have an elaborate test that opened a real TCP listening socket
# and then tried to measure its backlog by making connections to it. And most
# of the time, it worked. But no matter what we tried, it was always fragile,
# because it had to do things like use timeouts to guess when the listening
# queue was full, sometimes the CI hosts go into SYN-cookie mode (where there
# effectively is no backlog), sometimes the host might not be enough resources
# to give us the full requested backlog... it was a mess. So now we just check
# that the backlog argument is passed through correctly.
async def test_open_unix_listeners_backlog() -> None:
    fsf = FakeSocketFactory(99)
    tsocket.set_custom_socket_factory(fsf)
    for given, expected in [
        (None, 0xFFFF),
        (inf, 0xFFFF),
        (99999999, 0xFFFF),
        (10, 10),
        (1, 1),
    ]:
        listeners = await open_unix_listeners(0, backlog=given)
        assert listeners
        for listener in listeners:
            assert listener.socket.backlog == expected


async def test_open_unix_listeners_backlog_float_error() -> None:
    fsf = FakeSocketFactory(99)
    tsocket.set_custom_socket_factory(fsf)
    for should_fail in (0.0, 2.18, 3.14, 9.75):
        with pytest.raises(
            ValueError, match=f"Only accepts infinity, not {should_fail!r}"
        ):
            await open_unix_listeners(0, backlog=should_fail)
