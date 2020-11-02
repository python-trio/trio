import socket
import sys
import signal
import warnings

from .. import _core
from .._util import is_main_thread


def _has_warn_on_full_buffer():
    if sys.version_info < (3, 7):
        return False

    if "__pypy__" not in sys.builtin_module_names:
        # CPython has warn_on_full_buffer. Don't need to inspect.
        # Also, CPython doesn't support inspecting built-in functions.
        return True

    import inspect

    args_spec = inspect.getfullargspec(signal.set_wakeup_fd)
    return "warn_on_full_buffer" in args_spec.kwonlyargs


HAVE_WARN_ON_FULL_BUFFER = _has_warn_on_full_buffer()


class WakeupSocketpair:
    def __init__(self):
        self.wakeup_sock, self.write_sock = socket.socketpair()
        self.wakeup_sock.setblocking(False)
        self.write_sock.setblocking(False)
        # This somewhat reduces the amount of memory wasted queueing up data
        # for wakeups. With these settings, maximum number of 1-byte sends
        # before getting BlockingIOError:
        #   Linux 4.8: 6
        #   macOS (darwin 15.5): 1
        #   Windows 10: 525347
        # Windows you're weird. (And on Windows setting SNDBUF to 0 makes send
        # blocking, even on non-blocking sockets, so don't do that.)
        #
        # But, if we're on an old Python and can't control the signal module's
        # warn-on-full-buffer behavior, then we need to leave things alone, so
        # the signal module won't spam the console with spurious warnings.
        if HAVE_WARN_ON_FULL_BUFFER:
            self.wakeup_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1)
            self.write_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1)
        # On Windows this is a TCP socket so this might matter. On other
        # platforms this fails b/c AF_UNIX sockets aren't actually TCP.
        try:
            self.write_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        self.old_wakeup_fd = None

    def wakeup_thread_and_signal_safe(self):
        try:
            self.write_sock.send(b"\x00")
        except BlockingIOError:
            pass

    async def wait_woken(self):
        await _core.wait_readable(self.wakeup_sock)
        self.drain()

    def drain(self):
        try:
            while True:
                self.wakeup_sock.recv(2 ** 16)
        except BlockingIOError:
            pass

    def wakeup_on_signals(self):
        assert self.old_wakeup_fd is None
        if not is_main_thread():
            return
        fd = self.write_sock.fileno()
        if HAVE_WARN_ON_FULL_BUFFER:
            self.old_wakeup_fd = signal.set_wakeup_fd(fd, warn_on_full_buffer=False)
        else:
            self.old_wakeup_fd = signal.set_wakeup_fd(fd)
        if self.old_wakeup_fd != -1:
            warnings.warn(
                RuntimeWarning(
                    "It looks like Trio's signal handling code might have "
                    "collided with another library you're using. If you're "
                    "running Trio in guest mode, then this might mean you "
                    "should set host_uses_signal_set_wakeup_fd=True. "
                    "Otherwise, file a bug on Trio and we'll help you figure "
                    "out what's going on."
                )
            )

    def close(self):
        self.wakeup_sock.close()
        self.write_sock.close()
        if self.old_wakeup_fd is not None:
            signal.set_wakeup_fd(self.old_wakeup_fd)
