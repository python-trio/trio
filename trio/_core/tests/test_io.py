import pytest

import socket as stdlib_socket
import select
import random

from ... import _core
from ...testing import wait_all_tasks_blocked, Sequencer, assert_checkpoints
import trio

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


def using_fileno(fn):
    def fileno_wrapper(fileobj):
        return fn(fileobj.fileno())

    name = "<{} on fileno>".format(fn.__name__)
    fileno_wrapper.__name__ = fileno_wrapper.__qualname__ = name
    return fileno_wrapper


wait_readable_options = [trio.hazmat.wait_readable]
wait_writable_options = [trio.hazmat.wait_writable]
notify_closing_options = [trio.hazmat.notify_closing]

for options_list in [
    wait_readable_options, wait_writable_options, notify_closing_options
]:
    options_list += [using_fileno(f) for f in options_list]

# Decorators that feed in different settings for wait_readable / wait_writable
# / notify_closing.
# Note that if you use all three decorators on the same test, it will run all
# N**3 *combinations*
read_socket_test = pytest.mark.parametrize(
    "wait_readable", wait_readable_options, ids=lambda fn: fn.__name__
)
write_socket_test = pytest.mark.parametrize(
    "wait_writable", wait_writable_options, ids=lambda fn: fn.__name__
)
notify_closing_test = pytest.mark.parametrize(
    "notify_closing", notify_closing_options, ids=lambda fn: fn.__name__
)


# XX These tests are all a bit dicey because they can't distinguish between
# wait_on_{read,writ}able blocking the way it should, versus blocking
# momentarily and then immediately resuming.
@read_socket_test
@write_socket_test
async def test_wait_basic(socketpair, wait_readable, wait_writable):
    a, b = socketpair

    # They start out writable()
    with assert_checkpoints():
        await wait_writable(a)

    # But readable() blocks until data arrives
    record = []

    async def block_on_read():
        try:
            with assert_checkpoints():
                await wait_readable(a)
        except _core.Cancelled:
            record.append("cancelled")
        else:
            record.append("readable")
            assert a.recv(10) == b"x"

    async with _core.open_nursery() as nursery:
        nursery.start_soon(block_on_read)
        await wait_all_tasks_blocked()
        assert record == []
        b.send(b"x")

    fill_socket(a)

    # Now writable will block, but readable won't
    with assert_checkpoints():
        await wait_readable(b)
    record = []

    async def block_on_write():
        try:
            with assert_checkpoints():
                await wait_writable(a)
        except _core.Cancelled:
            record.append("cancelled")
        else:
            record.append("writable")

    async with _core.open_nursery() as nursery:
        nursery.start_soon(block_on_write)
        await wait_all_tasks_blocked()
        assert record == []
        drain_socket(b)

    # check cancellation
    record = []
    async with _core.open_nursery() as nursery:
        nursery.start_soon(block_on_read)
        await wait_all_tasks_blocked()
        nursery.cancel_scope.cancel()
    assert record == ["cancelled"]

    fill_socket(a)
    record = []
    async with _core.open_nursery() as nursery:
        nursery.start_soon(block_on_write)
        await wait_all_tasks_blocked()
        nursery.cancel_scope.cancel()
    assert record == ["cancelled"]


@read_socket_test
async def test_double_read(socketpair, wait_readable):
    a, b = socketpair

    # You can't have two tasks trying to read from a socket at the same time
    async with _core.open_nursery() as nursery:
        nursery.start_soon(wait_readable, a)
        await wait_all_tasks_blocked()
        with pytest.raises(_core.BusyResourceError):
            await wait_readable(a)
        nursery.cancel_scope.cancel()


@write_socket_test
async def test_double_write(socketpair, wait_writable):
    a, b = socketpair

    # You can't have two tasks trying to write to a socket at the same time
    fill_socket(a)
    async with _core.open_nursery() as nursery:
        nursery.start_soon(wait_writable, a)
        await wait_all_tasks_blocked()
        with pytest.raises(_core.BusyResourceError):
            await wait_writable(a)
        nursery.cancel_scope.cancel()


@read_socket_test
@write_socket_test
@notify_closing_test
async def test_interrupted_by_close(
    socketpair, wait_readable, wait_writable, notify_closing
):
    a, b = socketpair

    async def reader():
        with pytest.raises(_core.ClosedResourceError):
            await wait_readable(a)

    async def writer():
        with pytest.raises(_core.ClosedResourceError):
            await wait_writable(a)

    fill_socket(a)

    async with _core.open_nursery() as nursery:
        nursery.start_soon(reader)
        nursery.start_soon(writer)
        await wait_all_tasks_blocked()
        notify_closing(a)


@read_socket_test
@write_socket_test
async def test_socket_simultaneous_read_write(
    socketpair, wait_readable, wait_writable
):
    record = []

    async def r_task(sock):
        await wait_readable(sock)
        record.append("r_task")

    async def w_task(sock):
        await wait_writable(sock)
        record.append("w_task")

    a, b = socketpair
    fill_socket(a)
    async with _core.open_nursery() as nursery:
        nursery.start_soon(r_task, a)
        nursery.start_soon(w_task, a)
        await wait_all_tasks_blocked()
        assert record == []
        b.send(b"x")
        await wait_all_tasks_blocked()
        assert record == ["r_task"]
        drain_socket(b)
        await wait_all_tasks_blocked()
        assert record == ["r_task", "w_task"]


@read_socket_test
@write_socket_test
async def test_socket_actual_streaming(
    socketpair, wait_readable, wait_writable
):
    a, b = socketpair

    # Use a small send buffer on one of the sockets to increase the chance of
    # getting partial writes
    a.setsockopt(stdlib_socket.SOL_SOCKET, stdlib_socket.SO_SNDBUF, 10000)

    N = 1000000  # 1 megabyte
    MAX_CHUNK = 65536

    results = {}

    async def sender(sock, seed, key):
        r = random.Random(seed)
        sent = 0
        while sent < N:
            print("sent", sent)
            chunk = bytearray(r.randrange(MAX_CHUNK))
            while chunk:
                with assert_checkpoints():
                    await wait_writable(sock)
                this_chunk_size = sock.send(chunk)
                sent += this_chunk_size
                del chunk[:this_chunk_size]
        sock.shutdown(stdlib_socket.SHUT_WR)
        results[key] = sent

    async def receiver(sock, key):
        received = 0
        while True:
            print("received", received)
            with assert_checkpoints():
                await wait_readable(sock)
            this_chunk_size = len(sock.recv(MAX_CHUNK))
            if not this_chunk_size:
                break
            received += this_chunk_size
        results[key] = received

    async with _core.open_nursery() as nursery:
        nursery.start_soon(sender, a, 0, "send_a")
        nursery.start_soon(sender, b, 1, "send_b")
        nursery.start_soon(receiver, a, "recv_a")
        nursery.start_soon(receiver, b, "recv_b")

    assert results["send_a"] == results["recv_b"]
    assert results["send_b"] == results["recv_a"]
