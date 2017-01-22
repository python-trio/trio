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
    task1 = await _core.spawn(child, a)
    task2 = await _core.spawn(child, b)
    assert (await task1.join()).unwrap() == "ok"
    assert (await task2.join()).unwrap() == "ok"
