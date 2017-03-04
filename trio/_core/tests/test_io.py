import pytest

import socket as stdlib_socket
import select
import random

from ... import _core
from ...testing import wait_all_tasks_blocked, Sequencer, assert_yields

# Cross-platform tests for IO handling

def fill_socket(sock):
    try:
        while True:
            sock.send(b"x" * 65536)
    except BlockingIOError:
        pass

def drain_socket(sock):
    try:
        while True:
            sock.recv(65536)
    except BlockingIOError:
        pass

@pytest.fixture
def socketpair():
    pair = stdlib_socket.socketpair()
    for sock in pair:
        sock.setblocking(False)
    yield pair
    for sock in pair:
        sock.close()

wait_readable_options = [_core.wait_socket_readable]
wait_writable_options = [_core.wait_socket_writable]
if hasattr(_core, "wait_readable"):
    wait_readable_options.append(_core.wait_readable)
    async def wait_readable_fd(fileobj):
        return await _core.wait_readable(fileobj.fileno())
    wait_readable_options.append(wait_readable_fd)
if hasattr(_core, "wait_writable"):
    wait_writable_options.append(_core.wait_writable)
    async def wait_writable_fd(fileobj):
        return await _core.wait_writable(fileobj.fileno())
    wait_writable_options.append(wait_writable_fd)

# Decorators that feed in different settings for wait_readable / wait_writable.
# Note that if you use both decorators on the same test, it will run all
# N**2 *combinations*
read_socket_test = pytest.mark.parametrize(
    "wait_readable", wait_readable_options, ids=lambda fn: fn.__name__)
write_socket_test = pytest.mark.parametrize(
    "wait_writable", wait_writable_options, ids=lambda fn: fn.__name__)


async def test_wait_socket_type_checking(socketpair):
    a, b = socketpair

    # wait_socket_* accept actual socket objects, only
    for sock_fn in [
            _core.wait_socket_readable, _core.wait_socket_writable]:
        with pytest.raises(TypeError):
            await sock_fn(a.fileno())

        class AllegedSocket(stdlib_socket.socket):
            pass
        with AllegedSocket() as alleged_socket:
            with pytest.raises(TypeError):
                await sock_fn(alleged_socket)


# XX These tests are all a bit dicey because they can't distinguish between
# wait_on_{read,writ}able blocking the way it should, versus blocking
# momentarily and then immediately resuming.
@read_socket_test
@write_socket_test
async def test_wait_basic(socketpair, wait_readable, wait_writable):
    a, b = socketpair

    # They start out writable()
    with assert_yields():
        await wait_writable(a)

    # But readable() blocks until data arrives
    record = []
    async def block_on_read():
        try:
            with assert_yields():
                await wait_readable(a)
        except _core.Cancelled:
            record.append("cancelled")
        else:
            record.append("readable")
            return a.recv(10)
    async with _core.open_nursery() as nursery:
        t = nursery.spawn(block_on_read)
        await wait_all_tasks_blocked()
        assert record == []
        b.send(b"x")
    assert t.result.unwrap() == b"x"

    fill_socket(a)

    # Now writable will block, but readable won't
    with assert_yields():
        await wait_readable(b)
    record = []
    async def block_on_write():
        try:
            with assert_yields():
                await wait_writable(a)
        except _core.Cancelled:
            record.append("cancelled")
        else:
            record.append("writable")
    async with _core.open_nursery() as nursery:
        t = nursery.spawn(block_on_write)
        await wait_all_tasks_blocked()
        assert record == []
        drain_socket(b)

    # check cancellation
    record = []
    async with _core.open_nursery() as nursery:
        t = nursery.spawn(block_on_read)
        await wait_all_tasks_blocked()
        nursery.cancel_scope.cancel()
    assert record == ["cancelled"]

    fill_socket(a)
    record = []
    async with _core.open_nursery() as nursery:
        t = nursery.spawn(block_on_write)
        await wait_all_tasks_blocked()
        nursery.cancel_scope.cancel()
    assert record == ["cancelled"]


@read_socket_test
async def test_double_read(socketpair, wait_readable):
    a, b = socketpair

    # You can't have two tasks trying to read from a socket at the same time
    async with _core.open_nursery() as nursery:
        nursery.spawn(wait_readable, a)
        await wait_all_tasks_blocked()
        with pytest.raises(RuntimeError):
            await wait_readable(a)
        nursery.cancel_scope.cancel()

@write_socket_test
async def test_double_write(socketpair, wait_writable):
    a, b = socketpair

    # You can't have two tasks trying to write to a socket at the same time
    fill_socket(a)
    async with _core.open_nursery() as nursery:
        nursery.spawn(wait_writable, a)
        await wait_all_tasks_blocked()
        with pytest.raises(RuntimeError):
            await wait_writable(a)
        nursery.cancel_scope.cancel()


@read_socket_test
@write_socket_test
async def test_socket_simultaneous_read_write(
        socketpair, wait_readable, wait_writable):
    a, b = socketpair
    fill_socket(a)
    async with _core.open_nursery() as nursery:
        r_task = nursery.spawn(wait_readable, a)
        w_task = nursery.spawn(wait_writable, a)
        await wait_all_tasks_blocked()
        assert r_task.result is None
        assert w_task.result is None
        b.send(b"x")
        await r_task.wait()
        drain_socket(b)
        await w_task.wait()


@read_socket_test
@write_socket_test
async def test_socket_actual_streaming(
        socketpair, wait_readable, wait_writable):
    a, b = socketpair

    # Use a small send buffer on one of the sockets to increase the chance of
    # getting partial writes
    a.setsockopt(stdlib_socket.SOL_SOCKET, stdlib_socket.SO_SNDBUF, 10000)

    N = 1000000  # 1 megabyte
    MAX_CHUNK = 65536

    async def sender(sock, seed):
        r = random.Random(seed)
        sent = 0
        while sent < N:
            print("sent", sent)
            chunk = bytearray(r.randrange(MAX_CHUNK))
            while chunk:
                with assert_yields():
                    await wait_writable(sock)
                this_chunk_size = sock.send(chunk)
                sent += this_chunk_size
                del chunk[:this_chunk_size]
        sock.shutdown(stdlib_socket.SHUT_WR)
        return sent

    async def receiver(sock):
        received = 0
        while True:
            print("received", received)
            with assert_yields():
                await wait_readable(sock)
            this_chunk_size = len(sock.recv(MAX_CHUNK))
            if not this_chunk_size:
                break
            received += this_chunk_size
        return received

    async with _core.open_nursery() as nursery:
        send_a = nursery.spawn(sender, a, 0)
        send_b = nursery.spawn(sender, b, 1)
        recv_a = nursery.spawn(receiver, a)
        recv_b = nursery.spawn(receiver, b)

    assert send_a.result.unwrap() == recv_b.result.unwrap()
    assert send_b.result.unwrap() == recv_a.result.unwrap()
