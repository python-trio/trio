from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import trio.socket as tsocket
from trio import SocketListener
from trio._highlevel_open_unix_listeners import (
    open_unix_listeners,
)
from trio.testing import open_stream_to_socket_listener

assert (  # Skip type checking when on Windows
    sys.platform != "win32" or not TYPE_CHECKING
)


async def test_open_unix_listeners_basic() -> None:
    # Since we are on unix, we can use fun things like /tmp
    listeners = await open_unix_listeners("/tmp/test_socket.sock", backlog=0)
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

    for resource in [c1, c2, s1, s2, *listeners]:
        await resource.aclose()
