import pytest

import attr

import trio
import trio.testing
from .._util import acontextmanager
from .test_ssl import CLIENT_CTX, SERVER_CTX

from .._ssl_stream_helpers import open_ssl_tcp_stream

# this would be much simpler with a real fake network
# or just having trustme support for IP addresses so I could try connecting to
# 127.0.0.1

# Need to at least check making a successful connection, and making
# connections that fail CA and hostname validation.
#
# Also custom context and https_compatible I guess, though there isn't a whole
# lot that could go wrong here. Probably don't need to test
# happy_eyeballs_delay separately.

@attr.s
class FakeSocket:
    stream = attr.ib()

    async def connect(self, sockaddr):
        pass

    async def sendall(self, data):
        await self.stream.send_all(data)

    async def recv(self, max_bytes):
        return await self.stream.receive_some(max_bytes)

    def close(self):
        self.stream.forceful_close()

    # Stubs to make SocketStream happy:
    def setsockopt(self, *args, **kwargs):
        pass

    def getpeername(self, *args):
        pass

    type = trio.socket.SOCK_STREAM
    did_shutdown_SHUT_WR = False


# No matter who you connect to, you end up talking to an echo server with a
# cert for trio-test-1.example.com.
@attr.s
class FakeNetwork(trio.abc.HostnameResolver, trio.abc.SocketFactory):
    nursery = attr.ib()

    async def getaddrinfo(self, *args):
        return [(trio.socket.AF_INET,
                 trio.socket.SOCK_STREAM,
                 trio.socket.IPPROTO_TCP,
                 "",
                 ("1.1.1.1", 443))]

    async def getnameinfo(self, *args):  # pragma: no cover
        raise NotImplementedError

    def is_trio_socket(self, obj):
        return isinstance(obj, FakeSocket)

    def socket(self, family, type, proto):
        client_stream, server_stream = trio.testing.memory_stream_pair()
        self.nursery.spawn(self.echo_server, server_stream)
        return FakeSocket(client_stream)

    async def echo_server(self, raw_server_stream):
        ssl_server_stream = trio.ssl.SSLStream(
            raw_server_stream,
            SERVER_CTX,
            server_side=True,
        )
        while True:
            data = await ssl_server_stream.receive_some(10000)
            if not data:
                break
            await ssl_server_stream.send_all(data)


async def test_open_ssl_tcp_stream():
    async with trio.open_nursery() as nursery:
        network = FakeNetwork(nursery)
        trio.socket.set_custom_hostname_resolver(network)
        trio.socket.set_custom_socket_factory(network)

        # We don't have the right trust set up
        # (checks that ssl_context=None is doing some validation)
        stream = await open_ssl_tcp_stream("trio-test-1.example.org", 80)
        with pytest.raises(trio.BrokenStreamError):
            await stream.do_handshake()

        # We have the trust but not the hostname
        # (checks custom ssl_context + hostname checking)
        stream = await open_ssl_tcp_stream(
            "xyzzy.example.org", 80, ssl_context=CLIENT_CTX,
        )
        with pytest.raises(trio.BrokenStreamError):
            await stream.do_handshake()

        # This one should work!
        stream = await open_ssl_tcp_stream(
            "trio-test-1.example.org", 80,
            ssl_context=CLIENT_CTX,
        )
        await stream.send_all(b"x")
        assert await stream.receive_some(1) == b"x"
        await stream.graceful_close()

        # Check https_compatible settings are being passed through
        assert not stream._https_compatible
        stream = await open_ssl_tcp_stream(
            "trio-test-1.example.org", 80,
            ssl_context=CLIENT_CTX,
            https_compatible=True,
            # also, smoke test happy_eyeballs_delay
            happy_eyeballs_delay=1,
        )
        assert stream._https_compatible

        # We've left abandoned server tasks behind; clean them up.
        nursery.cancel_scope.cancel()
