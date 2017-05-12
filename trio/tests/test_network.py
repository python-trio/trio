import pytest

import socket as stdlib_socket

from .. import _core
from ..testing import check_half_closeable_stream, wait_all_tasks_blocked
from .._network import *
from .. import socket as tsocket

async def test_SocketStream_basics():
    # stdlib socket bad (even if connected)
    a, b = stdlib_socket.socketpair()
    with a, b:
        with pytest.raises(TypeError):
            SocketStream(a)

    # DGRAM socket bad
    with tsocket.socket(type=tsocket.SOCK_DGRAM) as sock:
        with pytest.raises(ValueError):
            SocketStream(sock)

    # disconnected socket bad
    with tsocket.socket() as sock:
        with pytest.raises(ValueError):
            SocketStream(sock)

    a, b = tsocket.socketpair()
    with a, b:
        s = SocketStream(a)
        assert s.socket is a

    # Use a real, connected socket to test socket options, because
    # socketpair() might give us a unix socket that doesn't support any of
    # these options
    with tsocket.socket() as listen_sock:
        listen_sock.bind(("127.0.0.1", 0))
        listen_sock.listen(1)
        with tsocket.socket() as client_sock:
            await client_sock.connect(listen_sock.getsockname())

            s = SocketStream(client_sock)

            # TCP_NODELAY enabled by default
            assert s.getsockopt(tsocket.IPPROTO_TCP, tsocket.TCP_NODELAY)
            # We can disable it though
            s.setsockopt(tsocket.IPPROTO_TCP, tsocket.TCP_NODELAY, False)
            assert not s.getsockopt(tsocket.IPPROTO_TCP, tsocket.TCP_NODELAY)


async def fill_stream(s):
    async def sender():
        while True:
            await s.send_all(b"x" * 10000)

    async def waiter(nursery):
        await wait_all_tasks_blocked()
        nursery.cancel_scope.cancel()

    async with _core.open_nursery() as nursery:
        nursery.spawn(sender)
        nursery.spawn(waiter, nursery)


async def test_SocketStream_and_socket_stream_pair_generic():
    async def stream_maker():
        return socket_stream_pair()

    async def clogged_stream_maker():
        left, right = socket_stream_pair()
        await fill_stream(left)
        await fill_stream(right)
        return left, right

    await check_half_closeable_stream(stream_maker, clogged_stream_maker)
