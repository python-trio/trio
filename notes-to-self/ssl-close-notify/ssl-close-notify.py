# Scenario:
# - TLS connection is set up successfully
# - client sends close_notify then closes socket
# - server receives the close_notify then attempts to send close_notify back
#
# On CPython, the last step raises BrokenPipeError. On PyPy, it raises
# SSLEOFError.
#
# SSLEOFError seems a bit perverse given that it's supposed to mean "EOF
# occurred in violation of protocol", and the client's behavior here is
# explicitly allowed by the RFCs. But maybe openssl is just perverse like
# that, and it's a coincidence that CPython and PyPy act differently here? I
# don't know if this is a bug or not.
#
# (Using: debian's CPython 3.5 or 3.6, and pypy3 5.8.0-beta)

import socket
import ssl
import threading

client_sock, server_sock = socket.socketpair()

client_done = threading.Event()

def server_thread_fn():
    server_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_ctx.load_cert_chain("trio-test-1.pem")
    server = server_ctx.wrap_socket(
        server_sock,
        server_side=True,
        suppress_ragged_eofs=False,
    )
    while True:
        data = server.recv(4096)
        print("server got:", data)
        if not data:
            print("server waiting for client to finish everything")
            client_done.wait()
            print("server attempting to send back close-notify")
            server.unwrap()
            print("server ok")
            break
        server.sendall(data)

server_thread = threading.Thread(target=server_thread_fn)
server_thread.start()

client_ctx = ssl.create_default_context(cafile="trio-test-CA.pem")
client = client_ctx.wrap_socket(
    client_sock,
    server_hostname="trio-test-1.example.org")


# Now we have two SSLSockets that have established an encrypted connection
# with each other

assert client.getpeercert() is not None
client.sendall(b"x")
assert client.recv(10) == b"x"

# The client sends a close-notify, and then immediately closes the connection
# (as explicitly permitted by the TLS RFCs).

# This is a slightly odd construction, but if you trace through the ssl module
# far enough you'll see that it's equivalent to calling SSL_shutdown() once,
# which generates the close_notify, and then immediately calling it again,
# which checks for the close_notify and then immediately raises
# SSLWantReadError because of course it hasn't arrived yet:
print("client sending close_notify")
client.setblocking(False)
try:
    client.unwrap()
except ssl.SSLWantReadError:
    print("client got SSLWantReadError as expected")
else:
    assert False
client.close()
client_done.set()
