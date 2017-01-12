import os
import select

class WakeupPipe:
    def __init__(self, unix_style_iomanager):
        self._unix_style_iomanager = unix_style_iomanager
        self._read_fd, self._write_fd = os.pipe()
        os.set_blocking(self._read_fd, False)
        os.set_blocking(self._write_fd, False)

    def wakeup_threadsafe(self):
        os.write(self._write_fd, b"\x00")

    async def until_woken(self):
        await self._unix_style_iomanager.until_readable(self._read_fd)
        # Drain the pipe:
        while os.read(self._read_fd, 2 ** 16):
            pass

    def close(self):
        os.close(self._read_fd)
        os.close(self._write_fd)

################################################################

_EPOLL_INTERESTS = (select.EPOLLIN | select.EPOLLOUT | select.EPOLLPRI
                   | select.EPOLLERR | select.EPOLLHUP | select.EPOLLRDHUP
                   | select.EPOLLRDBAND | select.WRNORM | select.WRBAND)

@attr.s(slots=True)
class _EpollWatcher:
    task = attr.ib()
    flags = attr.ib()

class EpollIOManager:
    def __init__(self):
        self._epoll = select.epoll()
        self._registered = {}

    # Public API:

    def poll(self, timeout):
        events = self._epoll.poll(timeout)
        for fd, flags in events:
            residual = set()
            for watcher in self._registered[fd]:
                if watcher.flags & flags:
                    XXreschedule(watcher.task)
                else:
                    residual.add(watcher)
            if residual:
                self._registered[fd] = residual
                self._update(fd, False)
            else:
                del self._registered[fd]

    def _update(self, fd, already_registered):
        # XX not sure if EPOLLEXCLUSIVE is actually safe... I think probably
        # we should use it here unconditionally, but:
        # https://stackoverflow.com/questions/41582560/how-does-epolls-epollexclusive-mode-interact-with-level-triggering
        flags = select.EPOLLONESHOT  # | select.EPOLLEXCLUSIVE
        watchers = self._registered[fd]
        if watchers:
            for watcher in watchers:
                flags |= watcher.flags
            if already_registered:
                self._epoll.modify(fd, flags)
            else:
                self._epoll.register(fd, flags)
        else:
            if already_registered:
                self._epoll.unregister(fd)
            del self._registered[fd]

    @types.coroutine
    def epoll_wait(self, fd, flags, status):
        if isinstance(fd, int):
            fd = fd.fileno()
        if flags != (flags & EPOLL_INTERESTS):
            raise ValueError("flags can only specify what you're interested in")
        if fd not in self._registered:
            self._registered[fd] = set()
            already_registered = False
        else:
            already_registered = True
        watcher = _EpollWatcher(task=XXcurrent_task(), flags=flags)
        self._registered[fd].add(watcher)
        self._update(fd, already_registered)
        def epoll_wait_cancel():
            self._registered[fd].remove(watcher)
            self._update(fd, True)
            # Or maybe this should be
            reschedule(..., cancellation)
        yield (epoll_wait_cancel, status)

    async def until_readable(self, fd, status="READ_WAIT"):
        await self.epoll_wait(fd, select.EPOLLIN, status)

    async def until_writable(self, fd, status="WRITE_WAIT"):
        await self.epoll_wait(fd, select.EPOLLOUT, status)

    def close(self):
        self._epoll.close()
