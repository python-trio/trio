import pytest

import socket as stdlib_socket
import select

from ... import _core
from ...testing import wait_run_loop_idle, Sequencer

# Cross-platform tests for IO handling

# XX These tests are all a bit dicey because they can't distinguish between
# wait_on_{read,writ}able blocking the way it should, versus blocking
# momentarily and then immediately resuming.
async def test_wait_socket():
    a, b = stdlib_socket.socketpair()
    a.setblocking(False)
    b.setblocking(False)

    with a, b:

        # Only sockets are allowed
        with pytest.raises(TypeError):
            await _core.wait_socket_writable(a.fileno())

        class AllegedSocket(stdlib_socket.socket):
            pass
        with AllegedSocket() as alleged_socket:
            with pytest.raises(TypeError):
                await _core.wait_socket_writable(alleged_socket)

        # They start out writable()
        await _core.wait_socket_writable(a)

        # But readable() blocks until data arrives
        record = []
        async def block_on_read():
            await _core.wait_socket_readable(a)
            record.append("readable")
            return a.recv(10)
        t = await _core.spawn(block_on_read)
        await wait_run_loop_idle()
        assert record == []
        b.send(b"x")
        assert (await t.join()).unwrap() == b"x"

        try:
            while True:
                a.send(b"x" * 65536)
        except BlockingIOError:
            pass

        # Now writable will block
        record = []
        async def block_on_write():
            await _core.wait_socket_writable(a)
            record.append("writable")
        t = await _core.spawn(block_on_write)
        await wait_run_loop_idle()
        assert record == []
        try:
            while True:
                b.recv(65536)
        except BlockingIOError:
            pass
        (await t.join()).unwrap()
