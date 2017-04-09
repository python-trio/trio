import pytest

from pathlib import Path
import threading
import socket as stdlib_socket
import ssl as stdlib_ssl

from .. import _core
from .. import ssl as tssl
from .. import socket as tsocket

from ..testing import assert_yields, wait_all_tasks_blocked


_cert_dir = Path(__file__).parent / "test_ssl_certs"
CA = str(_cert_dir / "trio-test-CA.pem")
CERT1 = str(_cert_dir / "trio-test-1.pem")
CERT2 = str(_cert_dir / "trio-test-2.pem")


def ssl_echo_server(sock, ctx):
    wrapped = ctx.wrap_socket(sock, server_side=True)
    while True:
        data = wrapped.recv(1024)
        if not data:
            # graceful shutdown
            wrapped.unwrap()
            return
        wrapped.sendall(data)


async def test_ssl_simple():
    a, b = stdlib_socket.socketpair()
    with a, b:
        a = tsocket.from_stdlib_socket(a)
        server_ctx = stdlib_ssl.create_default_context(
            stdlib_ssl.Purpose.CLIENT_AUTH,
        )
        server_ctx.load_cert_chain(CERT1)
        t = threading.Thread(target=ssl_echo_server, args=(b, server_ctx))
        t.start()

        client_ctx = stdlib_ssl.create_default_context(cafile=CA)
        s = tssl.SSLStream(
            a, client_ctx, server_hostname="trio-test-1.example.org")
        await s.sendall(b"x")
        assert await s.recv(10) == b"x"

        await s.graceful_close()
        t.join()
