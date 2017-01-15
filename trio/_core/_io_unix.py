import os
import select
from contextlib import contextmanager
import attr

from .. import _core
from . import _public, _hazmat
from ._traps import Interrupt, yield_indefinitely

class WakeupPipe:
    def __init__(self):
        self._read_fd, self._write_fd = os.pipe()
        os.set_blocking(self._read_fd, False)
        os.set_blocking(self._write_fd, False)

    def wakeup_threadsafe(self):
        os.write(self._write_fd, b"\x00")

    async def until_woken(self):
        await trio.hazmat.until_readable(self._read_fd)
        # Drain the pipe:
        while os.read(self._read_fd, 2 ** 16):
            pass

    def close(self):
        os.close(self._read_fd)
        os.close(self._write_fd)

################################################################

if hasattr(select, "epoll"):

    @attr.s(slots=True)
    class EpollWaiters:
        read_task = attr.ib(default=None)
        write_task = attr.ib(default=None)

        def flags(self):
            flags = 0
            if self.read_task is not None:
                flags |= select.EPOLLIN
            if self.write_task is not None:
                flags |= select.EPOLLOUT
            if not flags:
                return None
            # We always use EPOLLONESHOT
            # XX not sure if EPOLLEXCLUSIVE is actually safe... I think
            # probably we should use it here unconditionally, but:
            # https://stackoverflow.com/questions/41582560/how-does-epolls-epollexclusive-mode-interact-with-level-triggering
            flags |= select.EPOLLONESHOT  # | select.EPOLLEXCLUSIVE
            return flags

    @attr.s(slots=True)
    class EpollIOManager:
        _epoll = attr.ib(default=attr.Factory(select.epoll))
        # {fd: EpollWaiters}
        _registered = attr.ib(default=attr.Factory(dict))

        # Delegate wakeup functionality to WakeupPipe
        _wakeup = attr.ib(default=attr.Factory(WakeupPipe))
        def wakeup_threadsafe(self):
            self._wakeup.wakeup_threadsafe()
        async def until_woken(self):
            await self._wakeup.until_woken()

        def close(self):
            self._epoll.close()
            self._wakeup.close()

        # Called internally by the task runner:
        def handle_io(self, timeout):
            # max_events must be > 0 or epoll gets cranky
            max_events = max(1, len(self._registered))
            events = self._epoll.poll(timeout, max_events)
            for fd, flags in events:
                waiters = self._registered[fd]
                # Clever hack stolen from selectors.EpollSelector: an event
                # with EPOLLHUP or EPOLLERR flags wakes both readers and
                # writers.
                if flags & ~select.EPOLLIN and waiters.write_task is not None:
                    _core.reschedule(waiters.write_task)
                    waiters.write_task = None
                if flags & ~select.EPOLLOUT and waiters.read_task is not None:
                    _core.reschedule(waiters.read_task)
                    waiters.read_task = None
                new_flags = waiters.flags()
                if new_flags is None:
                    del self._registered[fd]
                else:
                    self._epoll.register(fd, new_flags)

        def _update_registrations(self, fd, currently_registered):
            waiters = self._registered[fd]
            flags = waiters.flags()
            if flags is None:
                del self._registered[fd]
                if currently_registered:
                    self._epoll.unregister(fd)
            else:
                if currently_registered:
                    self._epoll.modify(fd, flags)
                else:
                    self._epoll.register(fd, flags)

        # Public (hazmat) API:

        async def _epoll_wait(self, fd, status, attr_name):
            if not isinstance(fd, int):
                fd = fd.fileno()
            currently_registered = (fd in self._registered)
            if not currently_registered:
                self._registered[fd] = EpollWaiters()
            waiters = self._registered[fd]
            if getattr(waiters, attr_name) is not None:
                raise RuntimeError(
                    "another task is already reading / writing this fd")
            setattr(waiters, attr_name, _core.current_task())
            self._update_registrations(fd, currently_registered)
            def interrupt():
                setattr(self._registered[fd], attr_name, None)
                self._update_registrations(fd, True)
                return Interrupt.SUCCEEDED
            await yield_indefinitely(status, interrupt)

        @_public
        @_hazmat
        async def until_readable(self, fd, status="READ_WAIT"):
            await self._epoll_wait(fd, status, "read_task")

        @_public
        @_hazmat
        async def until_writable(self, fd, status="WRITE_WAIT"):
            await self._epoll_wait(fd, status, "write_task")

################################################################

if hasattr(select, "kqueue"):

    @attr.s(slots=True)
    class KqueueIOManager:
        _kqueue = attr.ib(default=attr.Factory(select.kqueue))
        # {(ident, filter): Task or Queue}
        _registered = attr.ib(default=attr.Factory(dict))

        # Delegate wakeup functionality to WakeupPipe
        _wakeup = attr.ib(default=attr.Factory(WakeupPipe))
        def wakeup_threadsafe(self):
            self._wakeup.wakeup_threadsafe()
        async def until_woken(self):
            await self._wakeup.until_woken()

        def close(self):
            self._kqueue.close()
            self._wakeup.close()

        def handle_io(self, timeout):
            # max_events must be > 0 or kqueue gets cranky
            max_events = max(1, len(self._registered))
            events = self._kqueue.control([], max_events, timeout)
            for event in events:
                key = event.ident, event.filter
                receiver = self._registered[key]
                if event.flags & select.KQ_EV_ONESHOT:
                    del self._registered[key]
                if type(receiver) is _core.Task:
                    _core.reschedule(receiver, _core.Value(event))
                else:
                    receiver.put_nowait(event)

        @_public
        @_hazmat
        @contextmanager
        def kevent_monitor(self, event):
            key = (event.ident, event.filter)
            if key in self._registered:
                raise ValueError(
                    "attempt to register multiple listeners for same "
                    "ident/filter pair")
            if event.flags & select.KQ_EV_ONESHOT:
                raise ValueError("for ONESHOT kevents use until_kevent_oneshot")
            q = _core.Queue(_core.Queue.UNLIMITED)
            self._registered[key] = q
            event.flags |= select.KQ_EV_ADD
            self._kqueue.control([event], 0)
            try:
                yield q
            finally:
                del self._registered[key]
                event.flags &= ~select.KQ_EV_ADD
                event.flags |= select.KQ_EV_DELETE
                self._kqueue.control([event], 0)

        @_public
        @_hazmat
        async def until_kevent_oneshot(self, event):
            key = (event.ident, event.filter)
            if key in self._registered:
                raise ValueError(
                    "attempt to register multiple listeners for same "
                    "ident/filter pair")
            event.flags |= select.KQ_EV_ONESHOT
            self._registered[key] = current_task()
            event.flags |= select.KQ_EV_ADD
            self._kqueue.control([event], 0)
            def interrupt():
                del self._registered[key]
                event.flags &= ~select.KQ_EV_ADD
                event.flags |= select.KQ_EV_DELETE
                self._kqueue.control([event], 0)
                return Interrupt.SUCCEEDED
            return await yield_indefinitely("KEVENT_WAIT", interrupt)

        @_public
        @_hazmat
        async def until_readable(self, fd, status="READ_WAIT"):
            if not isinstance(fd, int):
                fd = fd.fileno()
            event = select.kevent(fd, select.KQ_FILTER_READ)
            await self.until_kevent_oneshot(event)

        @_public
        @_hazmat
        async def until_writable(self, fd, status="WRITE_WAIT"):
            if not isinstance(fd, int):
                fd = fd.fileno()
            event = select.kevent(fd, select.KQ_FILTER_WRITE)
            await self.until_kevent_oneshot(event)
