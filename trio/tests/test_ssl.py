import pytest

from pathlib import Path
import threading
import socket as stdlib_socket
import ssl as stdlib_ssl
from contextlib import contextmanager

from .. import _core
from .. import ssl as tssl
from .. import socket as tsocket

from ..testing import assert_yields, wait_all_tasks_blocked


_cert_dir = Path(__file__).parent / "test_ssl_certs"
CA = str(_cert_dir / "trio-test-CA.pem")
CERT1 = str(_cert_dir / "trio-test-1.pem")
CERT2 = str(_cert_dir / "trio-test-2.pem")


def ssl_echo_serve_sync(sock, ctx, *, expect_fail=False):
    try:
        wrapped = ctx.wrap_socket(sock, server_side=True)
        while True:
            data = wrapped.recv(1024)
            if not data:
                # graceful shutdown
                wrapped.unwrap()
                return
            wrapped.sendall(data)
    except Exception as exc:
        if expect_fail:
            print("ssl_echo_serve_sync got error as expected:", exc)
        else:
            raise


# fixture that gives a socket connected to a trio-test-1 echo server (running
# in a thread)
@contextmanager
def ssl_echo_server(*, expect_fail=False):
    a, b = stdlib_socket.socketpair()
    with a, b:
        server_ctx = stdlib_ssl.create_default_context(
            stdlib_ssl.Purpose.CLIENT_AUTH,
        )
        server_ctx.load_cert_chain(CERT1)
        t = threading.Thread(
            target=ssl_echo_serve_sync,
            args=(b, server_ctx),
            kwargs={"expect_fail": expect_fail},
        )
        t.start()

        yield tsocket.from_stdlib_socket(a)
    # exiting the context manager closes the sockets, which should force the
    # thread to shut down
    t.join()


# Simple smoke test for handshake/send/receive/shutdown talking to a
# synchronous server, plus make sure that we do the bare minimum of
# certificate checking (even though this is really Python's responsibility)
async def test_ssl_client_basics():
    # Everything OK
    with ssl_echo_server() as sock:
        client_ctx = stdlib_ssl.create_default_context(cafile=CA)
        s = tssl.SSLStream(
            sock, client_ctx, server_hostname="trio-test-1.example.org")
        assert not s.server_side
        await s.sendall(b"x")
        assert await s.recv(1) == b"x"
        await s.graceful_close()

    # Didn't configure the CA file, should fail
    with ssl_echo_server(expect_fail=True) as sock:
        client_ctx = stdlib_ssl.create_default_context()
        s = tssl.SSLStream(
            sock, client_ctx, server_hostname="trio-test-1.example.org")
        assert not s.server_side
        with pytest.raises(tssl.SSLError):
            await s.sendall(b"x")

    # Trusted CA, but wrong host name
    with ssl_echo_server(expect_fail=True) as sock:
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

# - simultaneous read and write
# - simultaneous read and read, or write and write -> error

# - check attr forwarding code (getattr, setattr, dir)

# - check send_eof and wait_writable

# - check explicit handshake, repeated handshake

# - unwrap

# - sloppy and strict EOF modes
