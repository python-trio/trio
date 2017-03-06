import pytest

import os
import socket as stdlib_socket
import inspect

from .. import _core
from .. import socket as tsocket
from ..testing import assert_yields

################################################################
# utils
################################################################

class MonkeypatchedGAI:
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


################################################################
# basic re-exports
################################################################

def test_socket_has_some_reexports():
    assert tsocket.SOL_SOCKET == stdlib_socket.SOL_SOCKET
    assert tsocket.TCP_NODELAY == stdlib_socket.TCP_NODELAY
    assert tsocket.gaierror == stdlib_socket.gaierror
    assert tsocket.ntohs == stdlib_socket.ntohs


################################################################
# name resolution
################################################################

async def test_getaddrinfo(monkeygai):
    # Simple non-blocking non-error cases, ipv4 and ipv6:
    with assert_yields():
        res = await tsocket.getaddrinfo(
            "127.0.0.1", "12345", type=tsocket.SOCK_STREAM)
    def check(got, expected):
        # win32 returns 0 for the proto field
        def without_proto(gai_tup):
            return gai_tup[:2] + (0,) + gai_tup[3:]
        expected2 = [without_proto(gt) for gt in expected]
        assert got == expected or got == expected2

    check(res, [
        (tsocket.AF_INET,  # 127.0.0.1 is ipv4
         tsocket.SOCK_STREAM,
         tsocket.IPPROTO_TCP,
         "",
         ("127.0.0.1", 12345)),
    ])

    with assert_yields():
        res = await tsocket.getaddrinfo(
            "::1", "12345", type=tsocket.SOCK_DGRAM)
    check(res, [
        (tsocket.AF_INET6,
         tsocket.SOCK_DGRAM,
         tsocket.IPPROTO_UDP,
         "",
         ("::1", 12345, 0, 0)),
    ])

    monkeygai.set("x", "host", "port", family=0, type=0, proto=0, flags=0)
    with assert_yields():
        res = await tsocket.getaddrinfo("host", "port")
    assert res == "x"
    assert monkeygai.record[-1] == ("host", "port", 0, 0, 0, 0)

    # check raising an error from a non-blocking getaddrinfo
    with assert_yields():
        with pytest.raises(tsocket.gaierror) as excinfo:
            await tsocket.getaddrinfo("::1", "12345", type=-1)
    # Linux, Windows
    expected_errnos = {tsocket.EAI_SOCKTYPE}
    # MacOS
    if hasattr(tsocket, "EAI_BADHINTS"):
        expected_errnos.add(tsocket.EAI_BADHINTS)
    assert excinfo.value.errno in expected_errnos

    # check raising an error from a blocking getaddrinfo (exploits the fact
    # that monkeygai raises if it gets a non-numeric request it hasn't been
    # given an answer for)
    with assert_yields():
        with pytest.raises(RuntimeError):
            await tsocket.getaddrinfo("asdf", "12345")


async def test_getfqdn(monkeypatch):
    def my_getfqdn(name=""):
        return "x{}x".format(name)
    monkeypatch.setattr(stdlib_socket, "getfqdn", my_getfqdn)
    with assert_yields():
        assert await tsocket.getfqdn() == "xx"
    with assert_yields():
        assert await tsocket.getfqdn("foo") == "xfoox"


async def test_getnameinfo():
    ni_numeric = stdlib_socket.NI_NUMERICHOST | stdlib_socket.NI_NUMERICSERV
    with assert_yields():
        assert (await tsocket.getnameinfo(("127.0.0.1", 1234), ni_numeric)
                == ("127.0.0.1", "1234"))
    with assert_yields():
        with pytest.raises(tsocket.gaierror):
            # getnameinfo requires a numeric address as input
            await tsocket.getnameinfo(("google.com", 80), 0)


################################################################
# constructors
################################################################

async def test_from_stdlib_socket():
    sa, sb = stdlib_socket.socketpair()
    with sa, sb:
        ta = tsocket.from_stdlib_socket(sa)
        assert sa.fileno() == ta.fileno()
        await ta.send(b"xxx")
        assert sb.recv(3) == b"xxx"


async def test_from_fd():
    sa, sb = stdlib_socket.socketpair()
    ta = tsocket.fromfd(sa.fileno(), sa.family, sa.type, sa.proto)
    with sa, sb, ta:
        assert ta.fileno() != sa.fileno()
        await ta.send(b"xxx")
        assert sb.recv(3) == b"xxx"


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
    with a, b:
        async with _core.open_nursery() as nursery:
            task1 = nursery.spawn(child, a)
            task2 = nursery.spawn(child, b)
    assert task1.result.unwrap() == "ok"
    assert task2.result.unwrap() == "ok"


@pytest.mark.skipif(not hasattr(tsocket, "fromshare"), reason="windows only")
async def test_fromshare():
    a, b = tsocket.socketpair()
    with a, b:
        # share with ourselves
        shared = a.share(os.getpid())
        a2 = tsocket.fromshare(shared)
        with a2:
            assert a.fileno() != a2.fileno()
            await a2.send(b"xxx")
            assert await b.recv(3) == b"xxx"


async def test_socket():
    with tsocket.socket() as s:
        assert isinstance(s, tsocket.SocketType)
        assert s.family == tsocket.AF_INET

    with tsocket.socket(tsocket.AF_INET6, tsocket.SOCK_DGRAM) as s:
        assert isinstance(s, tsocket.SocketType)
        assert s.family == tsocket.AF_INET6


################################################################
# SocketType
################################################################
