import socket

from .. import _core

class WakeupSocketpair:
    def __init__(self):
        self.wakeup_sock, self.write_sock = socket.socketpair()
        self.wakeup_sock.setblocking(False)
        self.write_sock.setblocking(False)
        # This somewhat reduces the amount of memory wasted queueing up data
        # for wakeups. With these settings, maximum number of 1-byte sends
        # before getting BlockingIOError:
        #   Linux 4.8: 6
        #   MacOS (darwin 15.5): 1
        #   Windows 10: 525347
        # Windows you're weird. (And on Windows setting SNDBUF to 0 makes send
        # blocking, even on non-blocking sockets, so don't do that.)
        self.wakeup_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1)
        self.write_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1)

    def wakeup_thread_and_signal_safe(self):
        try:
            self.write_sock.send(b"\x00")
        except BlockingIOError:
            pass

    async def wait_woken(self):
        await _core.wait_socket_readable(self.wakeup_sock)
        self.drain()

    def drain(self):
        import time
        print("draining wakeup socket @", time.time())
        try:
            while True:
                data = self.wakeup_sock.recv(2 ** 16)
                print("drained", data)
        except BlockingIOError:
            print("done draining")
            pass

    def close(self):
        self.wakeup_sock.close()
        self.write_sock.close()
