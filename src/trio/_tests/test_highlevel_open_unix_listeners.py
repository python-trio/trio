from __future__ import annotations

import socket as stdlib_socket
import sys
import tempfile
from os import unlink
from os.path import exists
from typing import TYPE_CHECKING, cast

import pytest

import trio
import trio.socket as tsocket
from trio import (
    SocketListener,
    open_unix_listener,
    serve_unix,
)
from trio.testing import open_stream_to_socket_listener

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from trio.abc import SendStream

assert not TYPE_CHECKING or sys.platform != "win32"


skip_if_not_unix = pytest.mark.skipif(
    not hasattr(tsocket, "AF_UNIX"),
    reason="Needs unix socket support",
)


@pytest.fixture
def temp_unix_socket_path(tmp_path: Path) -> Generator[str, None, None]:
    """Fixture to create a temporary Unix socket path."""
    if sys.platform == "darwin":
        # On macos, opening unix socket will fail if name is too long
        temp_socket_path = tempfile.mkstemp(suffix=".sock")[1]
        # mkstemp makes a file, we just wanted a unique name
        unlink(temp_socket_path)
    else:
        temp_socket_path = str(tmp_path / "socket.sock")
    yield temp_socket_path
    # If test failed to delete file at the end, do it for them.
    if exists(temp_socket_path):
        unlink(temp_socket_path)


@skip_if_not_unix
async def test_open_unix_listener_basic(temp_unix_socket_path: str) -> None:
    listener = await open_unix_listener(temp_unix_socket_path)

    assert isinstance(listener, SocketListener)
    # Check that the listener is using the Unix socket family
    assert listener.socket.family == tsocket.AF_UNIX
    assert listener.socket.getsockname() == temp_unix_socket_path

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

    for resource in [c1, c2, s1, s2, listener]:
        await resource.aclose()


@skip_if_not_unix
async def test_open_unix_listener_specific_path(temp_unix_socket_path: str) -> None:
    listener = await open_unix_listener(temp_unix_socket_path)
    async with listener:
        assert listener.socket.getsockname() == temp_unix_socket_path


@skip_if_not_unix
async def test_open_unix_listener_rebind(temp_unix_socket_path: str) -> None:
    listener = await open_unix_listener(temp_unix_socket_path)
    sockaddr1 = listener.socket.getsockname()

    # Attempt to bind again to the same socket should fail
    with stdlib_socket.socket(tsocket.AF_UNIX) as probe:
        with pytest.raises(
            OSError,
            match=r"(Address (already )?in use|An attempt was made to access a socket in a way forbidden by its access permissions)$",
        ):
            probe.bind(temp_unix_socket_path)

    # Now use the listener to set up some connections
    c_established = await open_stream_to_socket_listener(listener)
    s_established = await listener.accept()
    await listener.aclose()

    # Attempt to bind again should succeed after closing the listener
    listener2 = await open_unix_listener(temp_unix_socket_path)
    sockaddr2 = listener2.socket.getsockname()

    assert sockaddr1 == sockaddr2
    assert s_established.socket.getsockname() == sockaddr2

    for resource in [listener2, c_established, s_established]:
        await resource.aclose()


@skip_if_not_unix
async def test_serve_unix(temp_unix_socket_path: str) -> None:
    async def handler(stream: SendStream) -> None:
        await stream.send_all(b"x")

    async with trio.open_nursery() as nursery:
        # nursery.start is incorrectly typed, awaiting #2773
        value = await nursery.start(serve_unix, handler, temp_unix_socket_path)
        assert isinstance(value, list)
        listeners = cast("list[SocketListener]", value)
        stream = await open_stream_to_socket_listener(listeners[0])
        async with stream:
            assert await stream.receive_some(1) == b"x"
            nursery.cancel_scope.cancel()
        for listener in listeners:
            await listener.aclose()


@pytest.mark.skipif(hasattr(tsocket, "AF_UNIX"), reason="Test for non-unix platforms")
async def test_error_on_no_unix(temp_unix_socket_path: str) -> None:
    with pytest.raises(
        RuntimeError,
        match=r"^Unix sockets are not supported on this platform$",
    ):
        async with await open_unix_listener(temp_unix_socket_path):
            pass
