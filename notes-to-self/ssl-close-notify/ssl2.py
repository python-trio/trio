# This demonstrates a PyPy bug:
#   https://bitbucket.org/pypy/pypy/issues/2578/

import socket
import ssl
import threading
import os

#client_sock, server_sock = socket.socketpair()
listen_sock = socket.socket()
listen_sock.bind(("127.0.0.1", 0))
listen_sock.listen(1)
client_sock = socket.socket()
client_sock.connect(listen_sock.getsockname())
server_sock, _ = listen_sock.accept()

server_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
server_ctx.load_cert_chain("trio-test-1.pem")
server = server_ctx.wrap_socket(
    server_sock,
    server_side=True,
    suppress_ragged_eofs=False,
    do_handshake_on_connect=False,
)

client_ctx = ssl.create_default_context(cafile="trio-test-CA.pem")
client = client_ctx.wrap_socket(
    client_sock,
    server_hostname="trio-test-1.example.org",
    suppress_ragged_eofs=False,
    do_handshake_on_connect=False,
)

server_handshake_thread = threading.Thread(target=server.do_handshake)
server_handshake_thread.start()
client_handshake_thread = threading.Thread(target=client.do_handshake)
client_handshake_thread.start()

server_handshake_thread.join()
client_handshake_thread.join()

# Now we have two SSLSockets that have established an encrypted connection
# with each other

assert client.getpeercert() is not None
client.sendall(b"x")
assert server.recv(10) == b"x"

# A few different ways to make attempts to read/write the socket's fd return
# weird failures at the operating system level

# Attempting to send on a socket after shutdown should raise EPIPE or similar
server.shutdown(socket.SHUT_WR)

# Attempting to read/write to the fd after it's closed should raise EBADF
#os.close(server.fileno())

# Attempting to read/write to an fd opened with O_DIRECT raises EINVAL in most
# cases (unless you're very careful with alignment etc. which openssl isn't)
#os.dup2(os.open("/tmp/blah-example-file", os.O_RDWR | os.O_CREAT | os.O_DIRECT), server.fileno())

# Sending or receiving
server.sendall(b"hello")
#server.recv(10)
