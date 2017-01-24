import socket

from .. import _core

class WakeupSocketpair:
    def __init__(self):
        self.wakeup_sock, self._write_sock = socket.socketpair()
        self.wakeup_sock.setblocking(False)
        self._write_sock.setblocking(False)
        # This somewhat reduces the amount of memory wasted queueing up data
        # for wakeups. With these settings, maximum number of 1-byte sends
        # before getting BlockingIOError:
        #   Linux 4.8: 6
        #   MacOS (darwin 15.5): 1
        #   Windows 10: 525347
        # Windows you're weird. (And on Windows setting SNDBUF to 0 makes send
        # blocking, even on non-blocking sockets, so don't do that.)
        self.wakeup_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1)
        self._write_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1)

    def wakeup_thread_and_signal_safe(self):
        try:
            self._write_sock.send(b"\x00")
        except BlockingIOError:
            pass

    async def wait_woken(self):
        await _core.wait_socket_readable(self.wakeup_sock)
        self.drain()

    def drain(self):
        try:
            while True:
                self.wakeup_sock.recv(2 ** 16)
        except BlockingIOError:
            pass

    def close(self):
        self.wakeup_sock.close()
        self._write_sock.close()
