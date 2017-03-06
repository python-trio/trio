import pytest

import socket as stdlib_socket
import inspect

from .. import _core
from .. import socket as tsocket
from ..testing import assert_yields

class MonkeypatchedFunc:
    def __init__(self, orig_getaddrinfo):
        self._orig_getaddrinfo = orig_getaddrinfo
        self._responses = {}
        self.record = []

    # get a normalized getaddrinfo argument tuple
    def _frozenbind(self, *args, **kwargs):
        sig = inspect.signature(self._orig_getaddrinfo)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        frozenbound = bound.args
        assert not bound.kwargs
        return frozenbound

    def set(self, response, *args, **kwargs):
        self._responses[self._frozenbind(*args, **kwargs)] = response

    def getaddrinfo(self, *args, **kwargs):
        bound = self._frozenbind(*args, **kwargs)
        self.record.append(bound)
        if bound in self._responses:
            return self._responses[bound]
        elif bound[-1] & stdlib_socket.AI_NUMERICHOST:
            return self._orig_getaddrinfo(*args, **kwargs)
        else:
            raise RuntimeError(
                "gai called with unexpected arguments {}".format(bound))


@pytest.fixture
def monkeygai(monkeypatch):
    controller = MonkeypatchedGAI(stdlib_socket.getaddrinfo)
    monkeypatch.setattr(stdlib_socket, "getaddrinfo", controller.getaddrinfo)
    return controller


async def test__try_sync():
    with assert_yields():
        async with tsocket._try_sync():
            pass

    with assert_yields():
        with pytest.raises(KeyError):
            async with tsocket._try_sync():
                raise KeyError

    async with tsocket._try_sync():
        raise BlockingIOError

    def _is_ValueError(exc):
        return isinstance(exc, ValueError)

    async with tsocket._try_sync(_is_ValueError):
        raise ValueError

    with assert_yields():
        with pytest.raises(BlockingIOError):
            async with tsocket._try_sync(_is_ValueError):
                raise BlockingIOError


def test_socket_has_some_reexports():
    assert tsocket.SOL_SOCKET == stdlib_socket.SOL_SOCKET
    assert tsocket.TCP_NODELAY == stdlib_socket.TCP_NODELAY
    assert tsocket.gaierror == stdlib_socket.gaierror
    assert tsocket.ntohs == stdlib_socket.ntohs


async def test_getaddrinfo(monkeygai):
    # Simple non-blocking non-error cases, ipv4 and ipv6:
    with assert_yields():
        res = await tsocket.getaddrinfo(
            "127.0.0.1", "12345", type=tsocket.SOCK_STREAM)
    assert res == [
        (tsocket.AF_INET,  # 127.0.0.1 is ipv4
         tsocket.SOCK_STREAM,
         tsocket.IPPROTO_TCP,
         "",
         ("127.0.0.1", 12345)),
    ]
    with assert_yields():
        res = await tsocket.getaddrinfo(
            "::1", "12345", type=tsocket.SOCK_DGRAM)
    assert res == [
        (tsocket.AF_INET6,
         tsocket.SOCK_DGRAM,
         tsocket.IPPROTO_UDP,
         "",
         ("::1", 12345, 0, 0)),
    ]

    monkeygai.set("x", "host", "port", family=0, type=0, proto=0, flags=0)
    with assert_yields():
        res = await tsocket.getaddrinfo("host", "port")
    assert res == "x"
    assert monkeygai.record[-1] == ("host", "port", 0, 0, 0, 0)

    # check raising an error from a non-blocking getaddrinfo
    with assert_yields():
        with pytest.raises(tsocket.gaierror) as excinfo:
            await tsocket.getaddrinfo("::1", "12345", type=-1)
    assert excinfo.value.errno == tsocket.EAI_SOCKTYPE

    # check raising an error from a blocking getaddrinfo (exploits the fact
    # that monkeygai raises if it gets a non-numeric request it hasn't been
    # given an answer for)
    with assert_yields():
        with pytest.raises(RuntimeError):
            await tsocket.getaddrinfo("asdf", "12345")


async def test_getfqdn(monkeypatch):



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
