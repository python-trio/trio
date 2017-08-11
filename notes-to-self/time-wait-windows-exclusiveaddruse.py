# On windows, what does SO_EXCLUSIVEADDRUSE actually do? Apparently not what
# the documentation says!
# See: https://stackoverflow.com/questions/45624916/
#
# Specifically, this script seems to demonstrate that it only creates
# conflicts between listening sockets, *not* lingering connected sockets.

import socket
from contextlib import contextmanager

@contextmanager
def report_outcome(tagline):
    try:
        yield
    except OSError as exc:
        print("{}: failed".format(tagline))
        print("    details: {!r}".format(exc))
    else:
        print("{}: succeeded".format(tagline))

# Set up initial listening socket
lsock = socket.socket()
lsock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
lsock.bind(("127.0.0.1", 0))
sockaddr = lsock.getsockname()
lsock.listen(10)

# Make connected client and server sockets
csock = socket.socket()
csock.connect(sockaddr)
ssock, _ = lsock.accept()

print("lsock", lsock.getsockname())
print("ssock", ssock.getsockname())

# Can't make a second listener while the first exists
probe = socket.socket()
probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
with report_outcome("rebind with existing listening socket"):
    probe.bind(sockaddr)

# Now we close the first listen socket, while leaving the connected sockets
# open:
lsock.close()
# This time binding succeeds (contra MSDN!)
probe = socket.socket()
probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
with report_outcome("rebind with live connected sockets"):
    probe.bind(sockaddr)
    probe.listen(10)
    print("probe", probe.getsockname())
    print("ssock", ssock.getsockname())
probe.close()

# Server-initiated close to trigger TIME_WAIT status
ssock.send(b"x")
assert csock.recv(1) == b"x"
ssock.close()
assert csock.recv(1) == b""

# And does the TIME_WAIT sock prevent binding?
probe = socket.socket()
probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
with report_outcome("rebind with TIME_WAIT socket"):
    probe.bind(sockaddr)
    probe.listen(10)
probe.close()
