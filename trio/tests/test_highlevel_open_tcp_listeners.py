import pytest

import socket as stdlib_socket
import errno

import attr

import trio
from trio import (
    open_tcp_listeners, serve_tcp, SocketListener, open_tcp_stream
)
from trio.testing import open_stream_to_socket_listener
from .. import socket as tsocket
from .._core.tests.tutil import slow, creates_ipv6, binds_ipv6


async def test_open_tcp_listeners_basic():
    listeners = await open_tcp_listeners(0)
    assert isinstance(listeners, list)
    for obj in listeners:
        assert isinstance(obj, SocketListener)
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


async def test_open_tcp_listeners_specific_port_specific_host():
    # Pick a port
    sock = tsocket.socket()
    await sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    sock.close()

    (listener,) = await open_tcp_listeners(port, host=host)
    async with listener:
        assert listener.socket.getsockname() == (host, port)


# Warning: this sleeps, and needs to use a real sleep -- MockClock won't
# work.
#
# Also, this measurement technique often works, but not always: sometimes SYN
# cookies get triggered, and then the backlog measured this way effectively
# becomes infinite. (In particular, this has been observed happening on
# Travis-CI.) To avoid this blowing up and eating all FDs / ephemeral ports,
# we put an upper limit on the number of connections we attempt, and if we hit
# it then we return the magic string "lots". Then
# test_open_tcp_listeners_backlog uses a special path to handle this, treating
# it as a success -- but at least we'll see in coverage if none of our test
# runs are actually running the test properly.
async def measure_backlog(listener, limit):
    client_streams = []
    try:
        while True:
            # Generally the response to the listen buffer being full is that
            # the SYN gets dropped, and the client retries after 1 second. So
            # we assume that any connect() call to localhost that takes >0.5
            # seconds indicates a dropped SYN.
            with trio.move_on_after(0.5) as cancel_scope:
                client_stream = await open_stream_to_socket_listener(listener)
                client_streams.append(client_stream)
            if cancel_scope.cancelled_caught:
                break
            if len(client_streams) >= limit:  # pragma: no cover
                return "lots"
    finally:
        # The need for "no cover" here is subtle: see
        # https://github.com/python-trio/trio/issues/522
        for client_stream in client_streams:  # pragma: no cover
            await client_stream.aclose()

    return len(client_streams)


@slow
async def test_open_tcp_listeners_backlog():
    # Operating systems don't necessarily use the exact backlog you pass
    async def check_backlog(nominal, required_min, required_max):
        listeners = await open_tcp_listeners(0, backlog=nominal)
        actual = await measure_backlog(listeners[0], required_max + 10)
        for listener in listeners:
            await listener.aclose()
        print("nominal", nominal, "actual", actual)
        if actual == "lots":  # pragma: no cover
            return
        assert required_min <= actual <= required_max

    await check_backlog(nominal=1, required_min=1, required_max=10)
    await check_backlog(nominal=11, required_min=11, required_max=20)


@binds_ipv6
async def test_open_tcp_listeners_ipv6_v6only():
    # Check IPV6_V6ONLY is working properly
    (ipv6_listener,) = await open_tcp_listeners(0, host="::1")
    _, port, *_ = ipv6_listener.socket.getsockname()

    with pytest.raises(OSError):
        await open_tcp_stream("127.0.0.1", port)


async def test_open_tcp_listeners_rebind():
    (l1,) = await open_tcp_listeners(0, host="127.0.0.1")
    sockaddr1 = l1.socket.getsockname()

    # Plain old rebinding while it's still there should fail, even if we have
    # SO_REUSEADDR set
    probe = stdlib_socket.socket()
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
    (l2,) = await open_tcp_listeners(sockaddr1[1], host="127.0.0.1")
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
    pass


@attr.s
class FakeSocket(tsocket.SocketType):
    family = attr.ib()
    type = attr.ib()
    proto = attr.ib()

    closed = attr.ib(default=False)
    poison_listen = attr.ib(default=False)

    def getsockopt(self, level, option):
        if (level, option) == (tsocket.SOL_SOCKET, tsocket.SO_ACCEPTCONN):
            return True
        assert False  # pragma: no cover

    def setsockopt(self, level, option, value):
        pass

    async def bind(self, sockaddr):
        pass

    def listen(self, backlog):
        if self.poison_listen:
            raise FakeOSError("whoops")

    def close(self):
        self.closed = True


@attr.s
class FakeSocketFactory:
    poison_after = attr.ib()
    sockets = attr.ib(factory=list)
    raise_on_family = attr.ib(factory=dict)  # family => errno

    def socket(self, family, type, proto):
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

    async def getaddrinfo(self, host, port, family, type, proto, flags):
        return [
            (family, tsocket.SOCK_STREAM, 0, "", (addr, port))
            for family, addr in self.family_addr_pairs
        ]


async def test_open_tcp_listeners_multiple_host_cleanup_on_error():
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
        await open_tcp_listeners(80, host="example.org")

    assert len(fsf.sockets) == 3
    for sock in fsf.sockets:
        assert sock.closed


async def test_open_tcp_listeners_port_checking():
    for host in ["127.0.0.1", None]:
        with pytest.raises(TypeError):
            await open_tcp_listeners(None, host=host)
        with pytest.raises(TypeError):
            await open_tcp_listeners(b"80", host=host)
        with pytest.raises(TypeError):
            await open_tcp_listeners("http", host=host)


async def test_serve_tcp():
    async def handler(stream):
        await stream.send_all(b"x")

    async with trio.open_nursery() as nursery:
        listeners = await nursery.start(serve_tcp, handler, 0)
        stream = await open_stream_to_socket_listener(listeners[0])
        async with stream:
            await stream.receive_some(1) == b"x"
            nursery.cancel_scope.cancel()


@pytest.mark.parametrize(
    "try_families", [
        {tsocket.AF_INET},
        {tsocket.AF_INET6},
        {tsocket.AF_INET, tsocket.AF_INET6},
    ]
)
@pytest.mark.parametrize(
    "fail_families", [
        {tsocket.AF_INET},
        {tsocket.AF_INET6},
        {tsocket.AF_INET, tsocket.AF_INET6},
    ]
)
async def test_open_tcp_listeners_some_address_families_unavailable(
    try_families, fail_families
):
    fsf = FakeSocketFactory(
        10,
        raise_on_family={
            family: errno.EAFNOSUPPORT
            for family in fail_families
        }
    )
    tsocket.set_custom_socket_factory(fsf)
    tsocket.set_custom_hostname_resolver(
        FakeHostnameResolver([(family, "foo") for family in try_families])
    )

    should_succeed = try_families - fail_families

    if not should_succeed:
        with pytest.raises(OSError) as exc_info:
            await open_tcp_listeners(80, host="example.org")

        assert "This system doesn't support" in str(exc_info.value)
        if isinstance(exc_info.value.__cause__, trio.MultiError):
            for subexc in exc_info.value.__cause__.exceptions:
                assert "nope" in str(subexc)
        else:
            assert isinstance(exc_info.value.__cause__, OSError)
            assert "nope" in str(exc_info.value.__cause__)
    else:
        listeners = await open_tcp_listeners(80)
        for listener in listeners:
            should_succeed.remove(listener.socket.family)
        assert not should_succeed


async def test_open_tcp_listeners_socket_fails_not_afnosupport():
    fsf = FakeSocketFactory(
        10,
        raise_on_family={
            tsocket.AF_INET: errno.EAFNOSUPPORT,
            tsocket.AF_INET6: errno.EINVAL,
        }
    )
    tsocket.set_custom_socket_factory(fsf)
    tsocket.set_custom_hostname_resolver(
        FakeHostnameResolver(
            [(tsocket.AF_INET, "foo"), (tsocket.AF_INET6, "bar")]
        )
    )

    with pytest.raises(OSError) as exc_info:
        await open_tcp_listeners(80, host="example.org")
    assert exc_info.value.errno == errno.EINVAL
    assert exc_info.value.__cause__ is None
    assert "nope" in str(exc_info.value)
