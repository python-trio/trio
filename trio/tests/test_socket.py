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
                "gai called with unexpected arguments {}".format(bound)
            )


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
    def check(got, expected):
        # win32 returns 0 for the proto field
        def without_proto(gai_tup):
            return gai_tup[:2] + (0,) + gai_tup[3:]

        expected2 = [without_proto(gt) for gt in expected]
        assert got == expected or got == expected2

    # Simple non-blocking non-error cases, ipv4 and ipv6:
    with assert_yields():
        res = await tsocket.getaddrinfo(
            "127.0.0.1", "12345", type=tsocket.SOCK_STREAM
        )

    check(res, [
        (tsocket.AF_INET,  # 127.0.0.1 is ipv4
         tsocket.SOCK_STREAM,
         tsocket.IPPROTO_TCP,
         "",
         ("127.0.0.1", 12345)),
    ])  # yapf: disable

    with assert_yields():
        res = await tsocket.getaddrinfo(
            "::1", "12345", type=tsocket.SOCK_DGRAM
        )
    check(res, [
        (tsocket.AF_INET6,
         tsocket.SOCK_DGRAM,
         tsocket.IPPROTO_UDP,
         "",
         ("::1", 12345, 0, 0)),
    ])  # yapf: disable

    monkeygai.set("x", b"host", "port", family=0, type=0, proto=0, flags=0)
    with assert_yields():
        res = await tsocket.getaddrinfo("host", "port")
    assert res == "x"
    assert monkeygai.record[-1] == (b"host", "port", 0, 0, 0, 0)

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


async def test_getnameinfo():
    # Trivial test:
    ni_numeric = stdlib_socket.NI_NUMERICHOST | stdlib_socket.NI_NUMERICSERV
    with assert_yields():
        got = await tsocket.getnameinfo(("127.0.0.1", 1234), ni_numeric)
    assert got == ("127.0.0.1", "1234")

    # getnameinfo requires a numeric address as input:
    with assert_yields():
        with pytest.raises(tsocket.gaierror):
            await tsocket.getnameinfo(("google.com", 80), 0)

    with assert_yields():
        with pytest.raises(tsocket.gaierror):
            await tsocket.getnameinfo(("localhost", 80), 0)

    # Blocking call to get expected values:
    host, service = stdlib_socket.getnameinfo(("127.0.0.1", 80), 0)

    # Some working calls:
    got = await tsocket.getnameinfo(("127.0.0.1", 80), 0)
    assert got == (host, service)

    got = await tsocket.getnameinfo(("127.0.0.1", 80), tsocket.NI_NUMERICHOST)
    assert got == ("127.0.0.1", service)

    got = await tsocket.getnameinfo(("127.0.0.1", 80), tsocket.NI_NUMERICSERV)
    assert got == (host, "80")


################################################################
# constructors
################################################################


async def test_from_stdlib_socket():
    sa, sb = stdlib_socket.socketpair()
    assert not tsocket.is_trio_socket(sa)
    with sa, sb:
        ta = tsocket.from_stdlib_socket(sa)
        assert tsocket.is_trio_socket(ta)
        assert sa.fileno() == ta.fileno()
        await ta.sendall(b"xxx")
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
        await ta.sendall(b"xxx")
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
            await a2.sendall(b"xxx")
            assert await b.recv(3) == b"xxx"


async def test_socket():
    with tsocket.socket() as s:
        assert isinstance(s, tsocket._SocketType)
        assert tsocket.is_trio_socket(s)
        assert s.family == tsocket.AF_INET

    with tsocket.socket(tsocket.AF_INET6, tsocket.SOCK_DGRAM) as s:
        assert isinstance(s, tsocket._SocketType)
        assert tsocket.is_trio_socket(s)
        assert s.family == tsocket.AF_INET6


################################################################
# _SocketType
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
    assert "recv" in dir(sock)
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
            assert isinstance(a2, tsocket._SocketType)
            assert a2.fileno() != a.fileno()
            a.close()
            await a2.sendall(b"xxx")
            assert await b.recv(3) == b"xxx"


async def test_SocketType_shutdown():
    a, b = tsocket.socketpair()
    with a, b:
        await a.sendall(b"xxx")
        assert await b.recv(3) == b"xxx"
        assert not a.did_shutdown_SHUT_WR
        assert not b.did_shutdown_SHUT_WR
        a.shutdown(tsocket.SHUT_WR)
        assert a.did_shutdown_SHUT_WR
        assert not b.did_shutdown_SHUT_WR
        assert await b.recv(3) == b""
        await b.sendall(b"yyy")
        assert await a.recv(3) == b"yyy"

    a, b = tsocket.socketpair()
    with a, b:
        assert not a.did_shutdown_SHUT_WR
        a.shutdown(tsocket.SHUT_RD)
        assert not a.did_shutdown_SHUT_WR

    a, b = tsocket.socketpair()
    with a, b:
        assert not a.did_shutdown_SHUT_WR
        a.shutdown(tsocket.SHUT_RDWR)
        assert a.did_shutdown_SHUT_WR


@pytest.mark.parametrize(
    "address, socket_type",
    [('127.0.0.1', tsocket.AF_INET),
     ('::1', tsocket.AF_INET6)]
)
async def test_SocketType_simple_server(address, socket_type):
    # listen, bind, accept, connect, getpeername, getsockname
    listener = tsocket.socket(socket_type)
    client = tsocket.socket(socket_type)
    with listener, client:
        listener.bind((address, 0))
        listener.listen(20)
        addr = listener.getsockname()[:2]
        async with _core.open_nursery() as nursery:
            nursery.spawn(client.connect, addr)
            accept_task = nursery.spawn(listener.accept)
        server, client_addr = accept_task.result.unwrap()
        with server:
            assert client_addr == server.getpeername() == client.getsockname()
            await server.sendall(b"xxx")
            assert await client.recv(3) == b"xxx"


async def test_SocketType_resolve():
    sock4 = tsocket.socket(family=tsocket.AF_INET)
    with assert_yields():
        got = await sock4.resolve_local_address((None, 80))
    assert got == ("0.0.0.0", 80)
    with assert_yields():
        got = await sock4.resolve_remote_address((None, 80))
    assert got == ("127.0.0.1", 80)

    sock6 = tsocket.socket(family=tsocket.AF_INET6)
    with assert_yields():
        got = await sock6.resolve_local_address((None, 80))
    assert got == ("::", 80, 0, 0)

    with assert_yields():
        got = await sock6.resolve_remote_address((None, 80))
    assert got == ("::1", 80, 0, 0)

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
        # Windows, MacOS
        expected_errnos = {tsocket.EAI_NONAME}
        # Linux
        if hasattr(tsocket, "EAI_ADDRFAMILY"):
            expected_errnos.add(tsocket.EAI_ADDRFAMILY)
        assert excinfo.value.errno in expected_errnos

        # A family where we know nothing about the addresses, so should just
        # pass them through. This should work on Linux, which is enough to
        # smoke test the basic functionality...
        try:
            netlink_sock = tsocket.socket(
                family=tsocket.AF_NETLINK, type=tsocket.SOCK_DGRAM
            )
        except (AttributeError, OSError):
            pass
        else:
            assert await getattr(netlink_sock, res)("asdf") == "asdf"

        with pytest.raises(ValueError):
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


# This tests all the complicated paths through _nonblocking_helper, using recv
# as a stand-in for all the methods that use _nonblocking_helper.
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


# This tests the complicated paths through connect
async def test_SocketType_connect_paths():
    with tsocket.socket() as sock:
        with assert_yields():
            with pytest.raises(ValueError):
                # Should be a tuple
                await sock.connect("localhost")

    # cancelled before we start
    with tsocket.socket() as sock:
        with assert_yields():
            with _core.open_cancel_scope() as cancel_scope:
                cancel_scope.cancel()
                with pytest.raises(_core.Cancelled):
                    await sock.connect(("127.0.0.1", 80))

    # Cancelled in between the connect() call and the connect completing
    with _core.open_cancel_scope() as cancel_scope:
        with tsocket.socket() as sock, tsocket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()

            # Swap in our weird subclass under the trio.socket._SocketType's
            # nose -- and then swap it back out again before we hit
            # wait_socket_writable, which insists on a real socket.
            class CancelSocket(stdlib_socket.socket):
                def connect(self, *args, **kwargs):
                    cancel_scope.cancel()
                    sock._sock = stdlib_socket.fromfd(
                        self.detach(), self.family, self.type
                    )
                    sock._sock.connect(*args, **kwargs)
                    # If connect *doesn't* raise, then pretend it did
                    raise BlockingIOError  # pragma: no cover

            sock._sock.close()
            sock._sock = CancelSocket()

            with assert_yields():
                with pytest.raises(_core.Cancelled):
                    await sock.connect(listener.getsockname())
            assert sock.fileno() == -1

    # Failed connect (hopefully after raising BlockingIOError)
    with tsocket.socket() as sock:
        with assert_yields():
            with pytest.raises(OSError):
                # TCP port 2 is not assigned. Pretty sure nothing will be
                # listening there. (We used to bind a port and then *not* call
                # listen() to ensure nothing was listening there, but it turns
                # out on MacOS if you do this it takes 30 seconds for the
                # connect to fail. Really. Also if you use a non-routable
                # address. This way fails instantly though. As long as nothing
                # is listening on port 2.)
                await sock.connect(("127.0.0.1", 2))


async def test_send_recv_variants():
    a, b = tsocket.socketpair()
    with a, b:
        # recv, including with flags
        await a.sendall(b"xxx")
        assert await b.recv(10, tsocket.MSG_PEEK) == b"xxx"
        assert await b.recv(10) == b"xxx"

        # recv_into
        await a.sendall(b"xxx")
        buf = bytearray(10)
        await b.recv_into(buf)
        assert buf == b"xxx" + b"\x00" * 7

        if hasattr(a, "sendmsg"):
            assert await a.sendmsg([b"xxx"], []) == 3
            assert await b.recv(10) == b"xxx"

    a = tsocket.socket(type=tsocket.SOCK_DGRAM)
    b = tsocket.socket(type=tsocket.SOCK_DGRAM)
    with a, b:
        a.bind(("127.0.0.1", 0))
        b.bind(("127.0.0.1", 0))
        # recvfrom
        assert await a.sendto(b"xxx", b.getsockname()) == 3
        (data, addr) = await b.recvfrom(10)
        assert data == b"xxx"
        assert addr == a.getsockname()

        # sendto + flags
        #
        # I can't find any flags that send() accepts... on Linux at least
        # passing MSG_MORE to send_some on a connected UDP socket seems to
        # just be ignored.
        #
        # But there's no MSG_MORE on Windows or MacOS. I guess send_some flags
        # are really not very useful, but at least this tests them a bit.
        if hasattr(tsocket, "MSG_MORE"):
            await a.sendto(b"xxx", tsocket.MSG_MORE, b.getsockname())
            await a.sendto(b"yyy", tsocket.MSG_MORE, b.getsockname())
            await a.sendto(b"zzz", b.getsockname())
            (data, addr) = await b.recvfrom(10)
            assert data == b"xxxyyyzzz"
            assert addr == a.getsockname()

        # recvfrom_into
        assert await a.sendto(b"xxx", b.getsockname()) == 3
        buf = bytearray(10)
        (nbytes, addr) = await b.recvfrom_into(buf)
        assert nbytes == 3
        assert buf == b"xxx" + b"\x00" * 7
        assert addr == a.getsockname()

        if hasattr(b, "recvmsg"):
            assert await a.sendto(b"xxx", b.getsockname()) == 3
            (data, ancdata, msg_flags, addr) = await b.recvmsg(10)
            assert data == b"xxx"
            assert ancdata == []
            assert msg_flags == 0
            assert addr == a.getsockname()

        if hasattr(b, "recvmsg_into"):
            assert await a.sendto(b"xyzw", b.getsockname()) == 4
            buf1 = bytearray(2)
            buf2 = bytearray(3)
            ret = await b.recvmsg_into([buf1, buf2])
            (nbytes, ancdata, msg_flags, addr) = ret
            assert nbytes == 4
            assert buf1 == b"xy"
            assert buf2 == b"zw" + b"\x00"
            assert ancdata == []
            assert msg_flags == 0
            assert addr == a.getsockname()

        if hasattr(a, "sendmsg"):
            assert await a.sendmsg([b"x", b"yz"], [], 0, b.getsockname()) == 3
            assert await b.recvfrom(10) == (b"xyz", a.getsockname())

    a = tsocket.socket(type=tsocket.SOCK_DGRAM)
    b = tsocket.socket(type=tsocket.SOCK_DGRAM)
    with a, b:
        b.bind(("127.0.0.1", 0))
        await a.connect(b.getsockname())
        # sendall on a connected udp socket; each call creates a separate
        # datagram
        await a.sendall(b"xxx")
        await a.sendall(b"yyy")
        assert await b.recv(10) == b"xxx"
        assert await b.recv(10) == b"yyy"


async def test_SocketType_sendall():
    BIG = 10000000

    a, b = tsocket.socketpair()
    with a, b:
        # Check a sendall that has to be split into multiple parts (on most
        # platforms... on Windows every send() either succeeds or fails as a
        # whole)
        async def sender():
            data = bytearray(BIG)
            await a.sendall(data)
            # sendall uses memoryviews internally, which temporarily "lock"
            # the object they view. If it doesn't clean them up properly, then
            # some bytearray operations might raise an error afterwards, which
            # would be a pretty weird and annoying side-effect to spring on
            # users. So test that this doesn't happen, by forcing the
            # bytearray's underlying buffer to be realloc'ed:
            data += bytes(BIG)
            # (Note: the above line of code doesn't do a very good job at
            # testing anything, because:
            # - on CPython, the refcount GC generally cleans up memoryviews
            #   for us even if we're sloppy.
            # - on PyPy3, at least as of 5.7.0, the memoryview code and the
            #   bytearray code conspire so that resizing never fails – if
            #   resizing forces the bytearray's internal buffer to move, then
            #   all memoryview references are automagically updated (!!).
            #   See:
            #   https://gist.github.com/njsmith/0ffd38ec05ad8e34004f34a7dc492227
            # But I'm leaving the test here in hopes that if this ever changes
            # and we break our implementation of sendall, then we'll get some
            # early warning...)

        async def receiver():
            # Make sure the sender fills up the kernel buffers and blocks
            await wait_all_tasks_blocked()
            nbytes = 0
            while nbytes < BIG:
                nbytes += len(await b.recv(BIG))
            assert nbytes == BIG

        async with _core.open_nursery() as nursery:
            nursery.spawn(sender)
            nursery.spawn(receiver)

        # We know that we received BIG bytes of NULs so far. Make sure that
        # was all the data in there.
        await a.sendall(b"e")
        assert await b.recv(10) == b"e"
        a.shutdown(tsocket.SHUT_WR)
        assert await b.recv(10) == b""


async def test_idna(monkeygai):
    # This is the encoding for "faß.de", which uses one of the characters that
    # IDNA 2003 handles incorrectly:
    monkeygai.set("ok faß.de", b"xn--fa-hia.de", 80)
    monkeygai.set("ok ::1", "::1", 80, flags=tsocket._NUMERIC_ONLY)
    monkeygai.set("ok ::1", b"::1", 80, flags=tsocket._NUMERIC_ONLY)
    # Some things that should not reach the underlying socket.getaddrinfo:
    monkeygai.set("bad", "fass.de", 80)
    # We always call socket.getaddrinfo with bytes objects:
    monkeygai.set("bad", "xn--fa-hia.de", 80)

    assert "ok ::1" == await tsocket.getaddrinfo("::1", 80)
    assert "ok ::1" == await tsocket.getaddrinfo(b"::1", 80)
    assert "ok faß.de" == await tsocket.getaddrinfo("faß.de", 80)
    assert "ok faß.de" == await tsocket.getaddrinfo("xn--fa-hia.de", 80)
    assert "ok faß.de" == await tsocket.getaddrinfo(b"xn--fa-hia.de", 80)


async def test_getprotobyname():
    # These are the constants used in IP header fields, so the numeric values
    # had *better* be stable across systems...
    assert await tsocket.getprotobyname("udp") == 17
    assert await tsocket.getprotobyname("tcp") == 6


async def test_custom_hostname_resolver(monkeygai):
    class CustomResolver:
        async def getaddrinfo(self, host, port, family, type, proto, flags):
            return ("custom_gai", host, port, family, type, proto, flags)

        async def getnameinfo(self, sockaddr, flags):
            return ("custom_gni", sockaddr, flags)

    cr = CustomResolver()

    assert tsocket.set_custom_hostname_resolver(cr) is None

    # Check that the arguments are all getting passed through.
    # We have to use valid calls to avoid making the underlying system
    # getaddrinfo cranky when it's used for NUMERIC checks.
    for vals in [
        (tsocket.AF_INET, 0, 0, 0),
        (0, tsocket.SOCK_STREAM, 0, 0),
        (0, 0, tsocket.IPPROTO_TCP, 0),
        (0, 0, 0, tsocket.AI_CANONNAME),
    ]:
        assert (
            await tsocket.getaddrinfo(
                "localhost", "foo", *vals
            ) == ("custom_gai", b"localhost", "foo", *vals)
        )

    # IDNA encoding is handled before calling the special object
    got = await tsocket.getaddrinfo("föö", "foo")
    expected = ("custom_gai", b"xn--f-1gaa", "foo", 0, 0, 0, 0)
    assert got == expected

    assert (await tsocket.getnameinfo("a", 0) == ("custom_gni", "a", 0))

    # We can set it back to None
    assert tsocket.set_custom_hostname_resolver(None) is cr

    # And now trio switches back to calling socket.getaddrinfo (specifically
    # our monkeypatched version of socket.getaddrinfo)
    monkeygai.set("x", b"host", "port", family=0, type=0, proto=0, flags=0)
    assert await tsocket.getaddrinfo("host", "port") == "x"


async def test_custom_socket_factory():
    class CustomSocketFactory:
        def socket(self, family, type, proto):
            return ("hi", family, type, proto)

        def is_trio_socket(self, obj):
            return obj == "foo"

    csf = CustomSocketFactory()

    assert not tsocket.is_trio_socket("foo")

    assert tsocket.set_custom_socket_factory(csf) is None

    assert tsocket.socket() == ("hi", tsocket.AF_INET, tsocket.SOCK_STREAM, 0)
    assert tsocket.socket(1, 2, 3) == ("hi", 1, 2, 3)

    # socket with fileno= doesn't call our custom method
    fd = stdlib_socket.socket().detach()
    wrapped = tsocket.socket(fileno=fd)
    assert hasattr(wrapped, "bind")
    wrapped.close()

    # Likewise for socketpair
    a, b = tsocket.socketpair()
    with a, b:
        assert hasattr(a, "bind")
        assert hasattr(b, "bind")

    assert tsocket.is_trio_socket("foo")

    assert tsocket.set_custom_socket_factory(None) is csf

    assert not tsocket.is_trio_socket("foo")
