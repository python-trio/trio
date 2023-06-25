import pytest

from functools import partial

import attr

import trio
from trio.socket import AF_INET, SOCK_STREAM, IPPROTO_TCP
import trio.testing
from .test_ssl import client_ctx, SERVER_CTX  # noqa: F401

from .._highlevel_ssl_helpers import (
    open_ssl_over_tcp_stream,
    open_ssl_over_tcp_listeners,
    serve_ssl_over_tcp,
)


async def echo_handler(stream):
    async with stream:
        try:
            while True:
                data = await stream.receive_some(10000)
                if not data:
                    break
                await stream.send_all(data)
        except trio.BrokenResourceError:
            pass


# Resolver that always returns the given sockaddr, no matter what host/port
# you ask for.
@attr.s
class FakeHostnameResolver(trio.abc.HostnameResolver):
    sockaddr = attr.ib()

    async def getaddrinfo(self, *args):
        return [(AF_INET, SOCK_STREAM, IPPROTO_TCP, "", self.sockaddr)]

    async def getnameinfo(self, *args):  # pragma: no cover
        raise NotImplementedError


# This uses serve_ssl_over_tcp, which uses open_ssl_over_tcp_listeners...
# noqa is needed because flake8 doesn't understand how pytest fixtures work.
async def test_open_ssl_over_tcp_stream_and_everything_else(client_ctx):  # noqa: F811
    async with trio.open_nursery() as nursery:
        (listener,) = await nursery.start(
            partial(serve_ssl_over_tcp, echo_handler, 0, SERVER_CTX, host="127.0.0.1")
        )
        async with listener:
            sockaddr = listener.transport_listener.socket.getsockname()
            hostname_resolver = FakeHostnameResolver(sockaddr)
            trio.socket.set_custom_hostname_resolver(hostname_resolver)

            # We don't have the right trust set up
            # (checks that ssl_context=None is doing some validation)
            stream = await open_ssl_over_tcp_stream("trio-test-1.example.org", 80)
            async with stream:
                with pytest.raises(trio.BrokenResourceError):
                    await stream.do_handshake()

            # We have the trust but not the hostname
            # (checks custom ssl_context + hostname checking)
            stream = await open_ssl_over_tcp_stream(
                "xyzzy.example.org", 80, ssl_context=client_ctx
            )
            async with stream:
                with pytest.raises(trio.BrokenResourceError):
                    await stream.do_handshake()

            # This one should work!
            stream = await open_ssl_over_tcp_stream(
                "trio-test-1.example.org", 80, ssl_context=client_ctx
            )
            async with stream:
                assert isinstance(stream, trio.SSLStream)
                assert stream.server_hostname == "trio-test-1.example.org"
                await stream.send_all(b"x")
                assert await stream.receive_some(1) == b"x"

            # Check https_compatible settings are being passed through
            assert not stream._https_compatible
            stream = await open_ssl_over_tcp_stream(
                "trio-test-1.example.org",
                80,
                ssl_context=client_ctx,
                https_compatible=True,
                # also, smoke test happy_eyeballs_delay
                happy_eyeballs_delay=1,
            )
            async with stream:
                assert stream._https_compatible

            # Stop the echo server
            nursery.cancel_scope.cancel()


async def test_open_ssl_over_tcp_listeners():
    (listener,) = await open_ssl_over_tcp_listeners(0, SERVER_CTX, host="127.0.0.1")
    async with listener:
        assert isinstance(listener, trio.SSLListener)
        tl = listener.transport_listener
        assert isinstance(tl, trio.SocketListener)
        assert tl.socket.getsockname()[0] == "127.0.0.1"

        assert not listener._https_compatible

    (listener,) = await open_ssl_over_tcp_listeners(
        0, SERVER_CTX, host="127.0.0.1", https_compatible=True
    )
    async with listener:
        assert listener._https_compatible
