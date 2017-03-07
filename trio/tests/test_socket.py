import pytest

import os
import socket as stdlib_socket
import inspect

from .. import _core
from .. import socket as tsocket
from ..testing import assert_yields, wait_all_tasks_blocked

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

    # rejects other types
    with pytest.raises(TypeError):
        tsocket.from_stdlib_socket(1)
    class MySocket(stdlib_socket.socket):
        pass
    mysock = MySocket()
    with pytest.raises(TypeError):
        tsocket.from_stdlib_socket(mysock)

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

async def test_SocketType_basics():
    sock = tsocket.socket()
    with sock as cm_enter_value:
        assert cm_enter_value is sock
        assert isinstance(sock.fileno(), int)
        assert not sock.get_inheritable()
        sock.set_inheritable(True)
        assert sock.get_inheritable()

        sock.setsockopt(tsocket.IPPROTO_TCP, tsocket.TCP_NODELAY, False)
        assert not sock.getsockopt(tsocket.IPPROTO_TCP, tsocket.TCP_NODELAY)
        sock.setsockopt(tsocket.IPPROTO_TCP, tsocket.TCP_NODELAY, True)
        assert sock.getsockopt(tsocket.IPPROTO_TCP, tsocket.TCP_NODELAY)
    # closed sockets have fileno() == -1
    assert sock.fileno() == -1

    # smoke test
    repr(sock)

    # detach
    with tsocket.socket() as sock:
        fd = sock.fileno()
        assert sock.detach() == fd
        assert sock.fileno() == -1

    # close
    sock = tsocket.socket()
    assert sock.fileno() >= 0
    sock.close()
    assert sock.fileno() == -1

    # share was tested above together with fromshare

    # check __dir__
    assert "family" in dir(sock)
    assert "send" in dir(sock)
    assert "setsockopt" in dir(sock)

    # our __getattr__ handles unknown names
    with pytest.raises(AttributeError):
        sock.asdf

    # type family proto
    stdlib_sock = stdlib_socket.socket()
    sock = tsocket.from_stdlib_socket(stdlib_sock)
    assert sock.type == stdlib_sock.type
    assert sock.family == stdlib_sock.family
    assert sock.proto == stdlib_sock.proto
    sock.close()


async def test_SocketType_dup():
    a, b = tsocket.socketpair()
    with a, b:
        a2 = a.dup()
        with a2:
            assert isinstance(a2, tsocket.SocketType)
            assert a2.fileno() != a.fileno()
            a.close()
            await a2.sendall(b"xxx")
            assert await b.recv(3) == b"xxx"


async def test_SocketType_shutdown():
    a, b = tsocket.socketpair()
    with a, b:
        await a.sendall(b"xxx")
        assert await b.recv(3) == b"xxx"
        a.shutdown(tsocket.SHUT_WR)
        assert await b.recv(3) == b""
        await b.sendall(b"yyy")
        assert await a.recv(3) == b"yyy"


async def test_SocketType_simple_server():
    # listen, bind, accept, connect, getpeername, getsockname
    with tsocket.socket() as listener, tsocket.socket() as client:
        listener.bind(("127.0.0.1", 0))
        listener.listen(20)
        addr = listener.getsockname()
        async with _core.open_nursery() as nursery:
            nursery.spawn(client.connect, addr)
            accept_task = nursery.spawn(listener.accept)
        server, client_addr = accept_task.result.unwrap()
        with server:
            assert client_addr == server.getpeername() == client.getsockname()
            await server.send(b"xxx")
            assert await client.recv(3) == b"xxx"


async def test_SocketType_resolve():
    sock4 = tsocket.socket(family=tsocket.AF_INET)
    with assert_yields():
        assert await sock4.resolve_local_address((None, 80)) == ("0.0.0.0", 80)
    with assert_yields():
        assert (await sock4.resolve_remote_address((None, 80))
                == ("127.0.0.1", 80))

    sock6 = tsocket.socket(family=tsocket.AF_INET6)
    with assert_yields():
        assert (await sock6.resolve_local_address((None, 80))
                == ("::", 80, 0, 0))
    with assert_yields():
        assert (await sock6.resolve_remote_address((None, 80))
                == ("::1", 80, 0, 0))

    # AI_PASSIVE only affects the wildcard address, so for everything else
    # resolve_local_address and resolve_remote_address should work the same:
    for res in ["resolve_local_address", "resolve_remote_address"]:
        async def s4res(*args):
            with assert_yields():
                return await getattr(sock4, res)(*args)
        async def s6res(*args):
            with assert_yields():
                return await getattr(sock6, res)(*args)

        assert await s4res(("1.2.3.4", "http")) == ("1.2.3.4", 80)
        assert await s6res(("1::2", "http")) == ("1::2", 80, 0, 0)

        assert await s6res(("1::2", 80, 1)) == ("1::2", 80, 1, 0)
        assert await s6res(("1::2", 80, 1, 2)) == ("1::2", 80, 1, 2)

        # V4 mapped addresses resolved if V6ONLY if False
        sock6.setsockopt(tsocket.IPPROTO_IPV6, tsocket.IPV6_V6ONLY, False)
        assert await s6res(("1.2.3.4", "http")) == ("::ffff:1.2.3.4", 80, 0, 0)

        # But not if it's true
        sock6.setsockopt(tsocket.IPPROTO_IPV6, tsocket.IPV6_V6ONLY, True)
        with pytest.raises(tsocket.gaierror) as excinfo:
            await s6res(("1.2.3.4", 80))
        assert excinfo.value.errno in {
            # Linux
            tsocket.EAI_ADDRFAMILY,
            # MacOS, Windows
            tsocket.EAI_NONAME,
        }

        # A family where we know nothing about the addresses, so should just
        # pass them through. Linux and Windows both seem to support AF_IRDA
        # well enough for this test to work.
        if hasattr(tsocket, "AF_IRDA"):
            irda_sock = tsocket.socket(family=tsocket.AF_IRDA)
            assert await getattr(irda_sock, res)("asdf") == "asdf"

        with pytest.raises(ValueError):
            print("hi")
            await s4res("1.2.3.4")
        with pytest.raises(ValueError):
            await s4res(("1.2.3.4",))
        with pytest.raises(ValueError):
            await s4res(("1.2.3.4", 80, 0, 0))
        with pytest.raises(ValueError):
            await s6res("1.2.3.4")
        with pytest.raises(ValueError):
            await s6res(("1.2.3.4",))
        with pytest.raises(ValueError):
            await s6res(("1.2.3.4", 80, 0, 0, 0))


async def test_SocketType_requires_preresolved(monkeypatch):
    sock = tsocket.socket()
    with pytest.raises(ValueError):
        sock.bind(("localhost", 0))

    # I don't think it's possible to actually get a gaierror from the way we
    # call getaddrinfo in _check_address, but just in case someone finds a
    # way, check that it propagates correctly
    def gai_oops(*args, **kwargs):
        raise tsocket.gaierror("nope!")
    monkeypatch.setattr(stdlib_socket, "getaddrinfo", gai_oops)
    with pytest.raises(tsocket.gaierror):
        sock.bind(("localhost", 0))


async def test_SocketType_non_blocking_paths():
    a, b = stdlib_socket.socketpair()
    with a, b:
        ta = tsocket.from_stdlib_socket(a)
        b.setblocking(False)

        # cancel before even calling
        b.send(b"1")
        with _core.open_cancel_scope() as cscope:
            cscope.cancel()
            with assert_yields():
                with pytest.raises(_core.Cancelled):
                    await ta.recv(10)
        # immedate success (also checks that the previous attempt didn't
        # actually read anything)
        with assert_yields():
            await ta.recv(10) == b"1"
        # immediate failure
        with assert_yields():
            with pytest.raises(TypeError):
                await ta.recv("haha")
        # block then succeed
        async def do_successful_blocking_recv():
            with assert_yields():
                assert await ta.recv(10) == b"2"
        async with _core.open_nursery() as nursery:
            nursery.spawn(do_successful_blocking_recv)
            await wait_all_tasks_blocked()
            b.send(b"2")
        # block then cancelled
        async def do_cancelled_blocking_recv():
            with assert_yields():
                with pytest.raises(_core.Cancelled):
                    await ta.recv(10)
        async with _core.open_nursery() as nursery:
            nursery.spawn(do_cancelled_blocking_recv)
            await wait_all_tasks_blocked()
            nursery.cancel_scope.cancel()
        # Okay, here's the trickiest one: we want to exercise the path where
        # the task is signaled to wake, goes to recv, but then the recv fails,
        # so it has to go back to sleep and try again. Strategy: have two
        # tasks waiting on two sockets (to work around the rule against having
        # two tasks waiting on the same socket), wake them both up at the same
        # time, and whichever one runs first "steals" the data from the
        # other:
        tb = tsocket.from_stdlib_socket(b)
        async def t1():
            with assert_yields():
                assert await ta.recv(1) == b"a"
            with assert_yields():
                assert await tb.recv(1) == b"b"
        async def t2():
            with assert_yields():
                assert await tb.recv(1) == b"b"
            with assert_yields():
                assert await ta.recv(1) == b"a"
        async with _core.open_nursery() as nursery:
            nursery.spawn(t1)
            nursery.spawn(t2)
            await wait_all_tasks_blocked()
            a.send(b"b")
            b.send(b"a")
            await wait_all_tasks_blocked()
            a.send(b"b")
            b.send(b"a")

# connect cancelled, interrupted -- probably requires monkeypatching
# socket.socket.connect
# - invalid arguments
# - cancelled before we start
# - raises InterruptedError 3 times then switches to actually working
# - connect() cancels and then issues the real connect
# - delayed error: connect to unused port on localhost
#   (I guess bind a socket but don't call listen, to get an unused port)

# recv recv_into recvfrom recvfrom_into recvmsg recvmsg_into
# send sendto sendmsg
# sendall

# create_connection
