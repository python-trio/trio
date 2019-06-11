# Tests for the special features of the epoll IOManager
# (Tests for common functionality are in test_io)

# epoll doesn't really have any special features ATM, so this is pretty short.

import pytest

import select
import socket as stdlib_socket

using_epoll = hasattr(select, "epoll")
pytestmark = pytest.mark.skipif(not using_epoll, reason="epoll platforms only")

from .test_io import fill_socket
from ... import _core
from ...testing import wait_all_tasks_blocked


async def test_epoll_statistics():
    a1, b1 = stdlib_socket.socketpair()
    a2, b2 = stdlib_socket.socketpair()
    a3, b3 = stdlib_socket.socketpair()
    for sock in [a1, b1, a2, b2, a3, b3]:
        sock.setblocking(False)
    with a1, b1, a2, b2, a3, b3:
        # let the call_soon_task settle down
        await wait_all_tasks_blocked()

        statistics = _core.current_statistics()
        print(statistics)
        assert statistics.io_statistics.backend == "epoll"
        # 1 for call_soon_task
        assert statistics.io_statistics.tasks_waiting_read == 1
        assert statistics.io_statistics.tasks_waiting_write == 0

        # We want:
        # - one socket with a writer blocked
        # - two sockets with a reader blocked
        # - a socket with both blocked
        fill_socket(a1)
        fill_socket(a3)
        async with _core.open_nursery() as nursery:
            nursery.start_soon(_core.wait_writable, a1)
            nursery.start_soon(_core.wait_readable, a2)
            nursery.start_soon(_core.wait_readable, b2)
            nursery.start_soon(_core.wait_writable, a3)
            nursery.start_soon(_core.wait_readable, a3)

            await wait_all_tasks_blocked()

            statistics = _core.current_statistics()
            print(statistics)
            # 1 for call_soon_task
            assert statistics.io_statistics.tasks_waiting_read == 4
            assert statistics.io_statistics.tasks_waiting_write == 2

            nursery.cancel_scope.cancel()
