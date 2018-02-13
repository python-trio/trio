import os
import socket
import tempfile

import pytest

from trio import open_unix_socket, Path
from trio._util import fspath

try:
    from socket import AF_UNIX
except ImportError:
    pytestmark = pytest.mark.skip("Needs unix socket support")


async def get_server_socket():
    name = Path() / tempfile.gettempdir() / "test.sock"
    try:
        await name.unlink()
    except OSError:
        pass

    serv_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    serv_sock.bind(fspath(name))  # bpo-32562
    serv_sock.listen(1)

    return name, serv_sock


async def _do_test_on_sock(serv_sock, unix_socket):
    # shared code between some tests
    client, _ = serv_sock.accept()
    await unix_socket.send_all(b"test")
    assert client.recv(2048) == b"test"

    client.sendall(b"response")
    received = await unix_socket.receive_some(2048)
    assert received == b"response"


async def test_open_bad_socket():
    # mktemp is marked as insecure, but that's okay, we don't want the file to
    # exist
    name = os.path.join(tempfile.gettempdir(), tempfile.mktemp())
    with pytest.raises(FileNotFoundError):
        await open_unix_socket(name)


async def test_open_unix_socket():
    name, serv_sock = await get_server_socket()
    unix_socket = await open_unix_socket(fspath(name))
    await _do_test_on_sock(serv_sock, unix_socket)


async def test_open_unix_socket_with_path():
    name, serv_sock = await get_server_socket()
    unix_socket = await open_unix_socket(name)
    await _do_test_on_sock(serv_sock, unix_socket)