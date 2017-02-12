import pytest

from .. import _core
from .. import socket as tsocket

async def test_socketpair_simple():
    async def child(sock):
        print("sending hello")
        await sock.sendall(b"hello!")
        buf = bytearray()
        while buf != b"hello!":
            print("reading", buf)
            buf += await sock.recv(10)
        return "ok"

    a, b = tsocket.socketpair()
    async with _core.open_nursery() as nursery:
        task1 = nursery.spawn(child, a)
        task2 = nursery.spawn(child, b)
    assert task1.result.unwrap() == "ok"
    assert task2.result.unwrap() == "ok"
