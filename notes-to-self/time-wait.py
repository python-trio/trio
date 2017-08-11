# what does SO_REUSEADDR do, exactly?

# Theory:
#
# - listen1 is bound to port P
# - listen1.accept() returns a connected socket server1, which is also bound
#   to port P
# - listen1 is closed
# - we attempt to bind listen2 to port P
# - this fails because server1 is still open, or still in TIME_WAIT, and you
#   can't use bind() to bind to a port that still has sockets on it, unless
#   both those sockets and the socket being bound have SO_REUSEADDR
#
# The standard way to avoid this is to set SO_REUSEADDR on all listening
# sockets before binding them. And this works, but for somewhat more
# complicated reasons than are often appreciated.
#
# In our scenario above it doesn't really matter for listen1 (assuming the
# port is initially unused).
#
# What is important is that it's set on *server1*. Setting it on listen1
# before calling bind() automatically accomplishes this, because SO_REUSEADDR
# is inherited by accept()ed sockets. But it also works to set it on listen1
# any time before calling accept(), or to set it on server1 directly.
#
# Also, it must be set on listen2 before calling bind(), or it will conflict
# with the lingering server1 socket.

import socket
import errno

import attr

@attr.s(repr=False)
class Options:
    listen1_early = attr.ib(default=None)
    listen1_middle = attr.ib(default=None)
    listen1_late = attr.ib(default=None)
    server = attr.ib(default=None)
    listen2 = attr.ib(default=None)

    def set(self, which, sock):
        value = getattr(self, which)
        if value is not None:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, value)

    def describe(self):
        info = []
        for f in attr.fields(self.__class__):
            value = getattr(self, f.name)
            if value is not None:
                info.append("{}={}".format(f.name, value))
        return "Set/unset: {}".format(", ".join(info))

def time_wait(options):
    print(options.describe())

    # Find a pristine port (one we can definitely bind to without
    # SO_REUSEADDR)
    listen0 = socket.socket()
    listen0.bind(("127.0.0.1", 0))
    sockaddr = listen0.getsockname()
    #print("  ", sockaddr)
    listen0.close()

    listen1 = socket.socket()
    options.set("listen1_early", listen1)
    listen1.bind(sockaddr)
    listen1.listen(1)

    options.set("listen1_middle", listen1)

    client = socket.socket()
    client.connect(sockaddr)

    options.set("listen1_late", listen1)

    server, _ = listen1.accept()

    options.set("server", server)

    # Server initiated close to trigger TIME_WAIT status
    server.close()
    assert client.recv(10) == b""
    client.close()

    listen1.close()

    listen2 = socket.socket()
    options.set("listen2", listen2)
    try:
        listen2.bind(sockaddr)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print("  -> EADDRINUSE")
        else:
            raise
    else:
        print("  -> ok")

time_wait(Options())
time_wait(Options(listen1_early=True, server=True, listen2=True))
time_wait(Options(listen1_early=True))
time_wait(Options(server=True))
time_wait(Options(listen2=True))
time_wait(Options(listen1_early=True, listen2=True))
time_wait(Options(server=True, listen2=True))
time_wait(Options(listen1_middle=True, listen2=True))
time_wait(Options(listen1_late=True, listen2=True))
time_wait(Options(listen1_middle=True, server=False, listen2=True))
