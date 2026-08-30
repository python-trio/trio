from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

import trio.socket as tsocket
from trio._highlevel_open_unix_listeners import (
    UnixSocketListener,
    open_unix_listeners,
)
from trio._highlevel_socket import SocketStream

assert not TYPE_CHECKING or sys.platform != "win32"

skip_if_not_unix = pytest.mark.skipif(
    not hasattr(tsocket, "AF_UNIX"),
    reason="Needs unix socket support",
)


async def open_stream_to_unix_socket_listener(
    socket_listener: UnixSocketListener,
    sockaddr: str,
) -> SocketStream:
    """Connect to the given :class:`~trio.UnixSocketListener`.

    This is particularly useful in tests when you want to let a server pick
    its own port, and then connect to it::

        listeners = await trio.open_tcp_listeners(0)
        client = await trio.testing.open_stream_to_socket_listener(listeners[0])

    Args:
      socket_listener (~trio.UnixSocketListener): The
          :class:`~trio.UnixSocketListener` to connect to.

    Returns:
      SocketStream: a stream connected to the given listener.

    """
    family = socket_listener.socket.family
    assert family == tsocket.AF_UNIX

    sock = tsocket.socket(family=family)
    await sock.connect(sockaddr)
    return SocketStream(sock)


@skip_if_not_unix
async def test_open_unix_listeners_basic() -> None:
    # Since we are on unix, we can use fun things like /tmp
    path = "/tmp/test_socket.sock"
    listeners = await open_unix_listeners(path, backlog=0)
    assert isinstance(listeners, list)
    for obj in listeners:
        assert obj.socket.family == tsocket.AF_UNIX
        # Does not work because of atomic overwrite
        # assert obj.socket.getsockname() == path

    listener = listeners[0]
    # Make sure the backlog is at least 2
    c1 = await open_stream_to_unix_socket_listener(listener, path)
    c2 = await open_stream_to_unix_socket_listener(listener, path)

    s1 = await listener.accept()
    s2 = await listener.accept()

    # Note that we don't know which client stream is connected to which server
    # stream
    await s1.send_all(b"x")
    await s2.send_all(b"x")
    assert await c1.receive_some(1) == b"x"
    assert await c2.receive_some(1) == b"x"

    for resource in [c1, c2, s1, s2, *listeners]:
        await resource.aclose()
