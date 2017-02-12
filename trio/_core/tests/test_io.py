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
        for sock_fn in [
                _core.wait_socket_readable, _core.wait_socket_writable]:
            with pytest.raises(TypeError):
                await sock_fn(a.fileno())

            class AllegedSocket(stdlib_socket.socket):
                pass
            with AllegedSocket() as alleged_socket:
                with pytest.raises(TypeError):
                    await sock_fn(alleged_socket)

        # They start out writable()
        await _core.wait_socket_writable(a)

        # But readable() blocks until data arrives
        record = []
        async def block_on_read():
            try:
                await _core.wait_socket_readable(a)
            except _core.Cancelled:
                record.append("cancelled")
            else:
                record.append("readable")
                return a.recv(10)
        async with _core.open_nursery() as nursery:
            t = nursery.spawn(block_on_read)
            await wait_run_loop_idle()
            assert record == []
            b.send(b"x")
        assert t.result.unwrap() == b"x"

        try:
            while True:
                a.send(b"x" * 65536)
        except BlockingIOError:
            pass

        # Now writable will block
        record = []
        async def block_on_write():
            try:
                await _core.wait_socket_writable(a)
            except _core.Cancelled:
                record.append("cancelled")
            else:
                record.append("writable")
        async with _core.open_nursery() as nursery:
            t = nursery.spawn(block_on_write)
            await wait_run_loop_idle()
            assert record == []
            try:
                while True:
                    b.recv(65536)
            except BlockingIOError:
                pass

        # check cancellation
        record = []
        async with _core.open_nursery() as nursery:
            t = nursery.spawn(block_on_read)
            await wait_run_loop_idle()
            nursery.cancel_scope.cancel()
        assert record == ["cancelled"]

        try:
            while True:
                a.send(b"x" * 65535)
        except BlockingIOError:
            pass
        record = []
        async with _core.open_nursery() as nursery:
            t = nursery.spawn(block_on_write)
            await wait_run_loop_idle()
            nursery.cancel_scope.cancel()
        assert record == ["cancelled"]
