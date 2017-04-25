import pytest

from pathlib import Path
import threading
import socket as stdlib_socket
import ssl as stdlib_ssl
from contextlib import contextmanager
import subprocess
import shutil
import os

from .. import _core
from .. import ssl as tssl
from .. import socket as tsocket

from ..testing import assert_yields, wait_all_tasks_blocked


ASSETS_DIR = Path(__file__).parent / "test_ssl_certs"
CA = str(ASSETS_DIR / "trio-test-CA.pem")
CERT1 = str(ASSETS_DIR / "trio-test-1.pem")
CERT2 = str(ASSETS_DIR / "trio-test-2.pem")

def ssl_echo_serve_sync(sock, *, expect_fail=False):
    try:
        server_ctx = stdlib_ssl.create_default_context(
            stdlib_ssl.Purpose.CLIENT_AUTH,
        )
        server_ctx.load_cert_chain(CERT1)
        wrapped = server_ctx.wrap_socket(sock, server_side=True)
        wrapped.do_handshake()
        while True:
            data = wrapped.recv(4096)
            if not data:
                # graceful shutdown
                wrapped.unwrap()
                return
            wrapped.sendall(data)
    except Exception as exc:
        if expect_fail:
            print("ssl_echo_serve_sync got error as expected:", exc)
        else:  # pragma: no cover
            raise
    else:
        if expect_fail:  # pragma: no cover
            print("failed to fail?!")


# fixture that gives a raw socket connected to a trio-test-1 echo server
# (running in a thread)
@contextmanager
def ssl_echo_server_raw(**kwargs):
    a, b = stdlib_socket.socketpair()
    with a, b:
        t = threading.Thread(
            target=ssl_echo_serve_sync,
            args=(b,),
            kwargs=kwargs,
        )
        t.start()

        yield tsocket.from_stdlib_socket(a)

    # exiting the context manager closes the sockets, which should force the
    # thread to shut down (possibly with an error)
    t.join()


# fixture that gives a properly set up SSLStream connected to a trio-test-1
# echo server (running in a thread)
@contextmanager
def ssl_echo_server(**kwargs):
    with ssl_echo_server_raw(**kwargs) as sock:
        client_ctx = stdlib_ssl.create_default_context(cafile=CA)
        yield tssl.SSLStream(
            sock, client_ctx, server_hostname="trio-test-1.example.org")


# experiment with using PyOpenSSL
def ssl_echo_serve_sync_pyopenssl(sock, *, expect_fail=False):
    # ref:
    # https://github.com/pyca/pyopenssl/blob/master/examples/simple/server.py
    # https://github.com/pyca/pyopenssl/blob/master/examples/simple/client.py
    from OpenSSL import SSL
    try:
        # Hard-code a version that supports renegotiation (since in the future
        # 1.3 won't)
        ctx = SSL.Context(SSL.TLSv1_2_METHOD)
        ctx.use_certificate_file(CERT1)
        ctx.use_privatekey_file(CERT1)
        wrapped = SSL.Connection(ctx, sock)
        wrapped.set_accept_state()
        wrapped.do_handshake()
        while True:
            try:
                data = wrapped.recv(1)
            except SSL.ZeroReturnError:
                wrapped.shutdown()
                return
            except SSL.WantReadError:
                # This sometimes happens during renegotiation, even on
                # blocking sockets.
                # See: https://github.com/pyca/pyopenssl/issues/190
                continue
            if data == b"\xff":
                if not wrapped.renegotiate_pending():
                    # Request that the next IO trigger the start of a
                    # renegotiation
                    print("starting renegotiation")
                    assert wrapped.renegotiate()
                else:
                    print("not starting renegotiation b/c last is still going")
            wrapped.send(data)
    except Exception as exc:
        if expect_fail:
            print("ssl_echo_serve_sync got error as expected:", repr(exc))
        else:
            raise
    else:
        if expect_fail:
            print("failed to fail?!")


@contextmanager
def ssl_echo_server_pyopenssl(**kwargs):
    a, b = stdlib_socket.socketpair()
    with a, b:
        t = threading.Thread(
            target=ssl_echo_serve_sync_pyopenssl,
            args=(b,),
            kwargs=kwargs,
        )
        t.start()

        client_ctx = stdlib_ssl.create_default_context(cafile=CA)
        tsock = tsocket.from_stdlib_socket(a)
        yield tssl.SSLStream(
            tsock, client_ctx, server_hostname="trio-test-1.example.org")

    # exiting the context manager closes the sockets, which should force the
    # thread to shut down (possibly with an error)
    t.join()


needs_java = pytest.mark.skipif(shutil.which("java") is None, reason="need java")

@contextmanager
def ssl_echo_server_java(**kwargs):
    p = subprocess.Popen(
        ["java", "SSLEchoServer", CERT1.replace("pem", "pkcs12")],
        stdout=subprocess.PIPE,
        universal_newlines=True,
        env={**os.environ, "CLASSPATH": str(ASSETS_DIR)},
    )
    try:
        port = int(p.stdout.readline())

        with stdlib_socket.create_connection(("127.0.0.1", port)) as ssock:
            tsock = tsocket.from_stdlib_socket(ssock)
            client_ctx = tssl.create_default_context(cafile=CA)
            yield tssl.SSLStream(
                tsock, client_ctx, server_hostname="trio-test-1.example.org")
    finally:
        p.kill()
        p.wait()


# Simple smoke test for handshake/send/receive/shutdown talking to a
# synchronous server, plus make sure that we do the bare minimum of
# certificate checking (even though this is really Python's responsibility)
async def test_ssl_client_basics():
    # Everything OK
    with ssl_echo_server() as s:
        assert not s.server_side
        await s.sendall(b"x")
        assert await s.recv(1) == b"x"
        await s.graceful_close()

    # Didn't configure the CA file, should fail
    with ssl_echo_server_raw(expect_fail=True) as sock:
        client_ctx = stdlib_ssl.create_default_context()
        s = tssl.SSLStream(
            sock, client_ctx, server_hostname="trio-test-1.example.org")
        assert not s.server_side
        with pytest.raises(tssl.SSLError):
            await s.sendall(b"x")

    # Trusted CA, but wrong host name
    with ssl_echo_server_raw(expect_fail=True) as sock:
        client_ctx = stdlib_ssl.create_default_context(cafile=CA)
        s = tssl.SSLStream(
            sock, client_ctx, server_hostname="trio-test-2.example.org")
        assert not s.server_side
        with pytest.raises(tssl.CertificateError):
            await s.sendall(b"x")

async def test_ssl_server_basics():
    a, b = stdlib_socket.socketpair()
    with a, b:
        server_sock = tsocket.from_stdlib_socket(b)
        server_ctx = tssl.create_default_context(tssl.Purpose.CLIENT_AUTH)
        server_ctx.load_cert_chain(CERT2)
        server_stream = tssl.SSLStream(
            server_sock, server_ctx, server_side=True)
        assert server_stream.server_side

        def client():
            client_ctx = stdlib_ssl.create_default_context(cafile=CA)
            client_sock = client_ctx.wrap_socket(
                a, server_hostname="trio-test-2.example.org")
            client_sock.sendall(b"x")
            assert client_sock.recv(1) == b"y"
            client_sock.sendall(b"z")
            client_sock.unwrap()
        t = threading.Thread(target=client)
        t.start()

        assert await server_stream.recv(1) == b"x"
        await server_stream.sendall(b"y")
        assert await server_stream.recv(1) == b"z"
        assert await server_stream.recv(1) == b""
        await server_stream.graceful_close()

        t.join()


async def test_attributes():
    with ssl_echo_server_raw(expect_fail=True) as sock:
        good_ctx = stdlib_ssl.create_default_context(cafile=CA)
        bad_ctx = stdlib_ssl.create_default_context()
        s = tssl.SSLStream(
            sock, good_ctx, server_hostname="trio-test-1.example.org")

        assert s.wrapped_stream is sock

        # Forwarded attribute getting
        assert s.context is good_ctx
        assert s.server_side == False
        assert s.server_hostname == "trio-test-1.example.org"
        with pytest.raises(AttributeError):
            s.asfdasdfsa

        # __dir__
        assert "wrapped_stream" in dir(s)
        assert "context" in dir(s)

        # Setting the attribute goes through to the underlying object

        # most attributes on SSLObject are read-only
        with pytest.raises(AttributeError):
            s.server_side = True
        with pytest.raises(AttributeError):
            s.server_hostname = "asdf"

        # but .context is *not*. Check that we forward attribute setting by
        # making sure that after we set the bad context our handshake indeed
        # fails:
        s.context = bad_ctx
        assert s.context is bad_ctx
        with pytest.raises(tssl.SSLError):
            await s.do_handshake()


async def test_send_eof():
    with ssl_echo_server(expect_fail=True) as s:
        assert not s.can_send_eof
        await s.do_handshake()
        with pytest.raises(RuntimeError):
            await s.send_eof()
        await s.graceful_close()


async def test_full_duplex_basics():
    CHUNKS = 100
    # bigger than the echo server's recv limit
    CHUNK_SIZE = 65536
    EXPECTED = CHUNKS * CHUNK_SIZE

    sent = bytearray()
    received = bytearray()
    async def sender(s):
        nonlocal sent
        for i in range(CHUNKS):
            print(i)
            chunk = bytes([i] * CHUNK_SIZE)
            sent += chunk
            await s.sendall(chunk)

    async def receiver(s):
        nonlocal received
        while len(received) < EXPECTED:
            chunk = await s.recv(CHUNK_SIZE // 2)
            received += chunk

    with ssl_echo_server() as s:
        async with _core.open_nursery() as nursery:
            nursery.spawn(sender, s)
            nursery.spawn(receiver, s)
            # And let's have some doing handshakes too, everyone
            # simultaneously
            nursery.spawn(s.do_handshake)
            nursery.spawn(s.do_handshake)

        await s.graceful_close()

    assert len(sent) == len(received) == EXPECTED
    assert sent == received


@needs_java
async def test_renegotiation():
    with ssl_echo_server_pyopenssl() as s:
        print("-- 1")
        await s.sendall(b"a")
        print("-- 2")
        assert await s.recv(1) == b"a"
        print("-- 3")
        await s.sendall(b"\xff")
        print("-- 4")
        assert await s.recv(1) == b"\xff"
        print("-- 5")
        await s.sendall(b"a")
        print("-- 6")
        assert await s.recv(1) == b"a"

        print("-- 7")
        await s.sendall(b"\xff")

        print("-- 8")
        async def send_a():
            print("send_a")
            await s.sendall(b"a")

        async def recv_ff():
            print("recv_ff")
            assert await s.recv(1) == b"\xff"

        async with _core.open_nursery() as nursery:
            nursery.spawn(send_a)
            nursery.spawn(recv_ff)
        print("-- 9")
        assert await s.recv(1) == b"a"

        print("-- 10")
        await s.sendall(b"b")
        print("-- 11")
        assert await s.recv(1) == b"b"

        print("-- 12")
        async def send_ff():
            print("send_ff")
            await s.sendall(b"\xff")

        for _ in range(10):
            async with _core.open_nursery() as nursery:
                nursery.spawn(send_ff)
                nursery.spawn(recv_ff)
            # freezes without this? I guess something bad about starting a new
            # renegotiation while the last one is still going...
            await s.sendall(b"a")
            assert await s.recv(1) == b"a"

        print("-- 13")
        async def send_lots_of_ffa(count):
            print("send_lots_of_ffa")
            await s.sendall(b"\xffa" * count)

        async def recv_lots_of_ffa(count):
            expected = b"\xffa" * count
            got = bytearray()
            while len(got) < len(expected):
                got += await s.recv(1)
            assert got == expected

        async with _core.open_nursery() as nursery:
            nursery.spawn(send_lots_of_ffa, 10)
            nursery.spawn(recv_lots_of_ffa, 10)

        print("--")
        await s.sendall(b"b")
        assert await s.recv(1) == b"b"

        print("closing")
        await s.graceful_close()

# assert checkpoints

# - simultaneous read and read, or write and write -> error

# check wait_writable (and write + wait_writable should also error)

# unwrap, switching protocols. ...what if we read too much? I guess unwrap
# should also return the residual data from the incoming BIO?

# - sloppy and strict EOF modes

# maybe some tests with a stream that writes and receives in small pieces, so
# there's lots of looping and retrying?

# check getpeercert(), probably need to work around:
# https://bugs.python.org/issue29334
