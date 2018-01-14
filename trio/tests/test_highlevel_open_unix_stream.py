import socket
import tempfile

from trio import open_unix_socket, Path


async def test_open_unix_socket():
    name = Path() / tempfile.gettempdir() / "test.sock"
    try:
        await name.unlink()
    except OSError:
        pass

    # server socket
    serv_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    serv_sock.bind(name.__fspath__())
    serv_sock.listen(1)

    # for some reason the server socket can accept the connection AFTER it has
    # been opened, so use that to test here
    unix_socket = await open_unix_socket(name.__fspath__())
    client, _ = serv_sock.accept()
    await unix_socket.send_all(b"test")
    assert client.recv(2048) == b"test"

    client.sendall(b"response")
    received = await unix_socket.receive_some(2048)
    assert received == b"response"
