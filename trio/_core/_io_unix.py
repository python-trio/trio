import sys
import fcntl
import os
import select
from contextlib import contextmanager
import attr

from .. import _core
from . import _public, _hazmat
from ._keyboard_interrupt import LOCALS_KEY_KEYBOARD_INTERRUPT_SAFE

def maybe_shrink_pipe(fd):
    # Try to set the pipe size as small as possible -- no point in having
    # a giant kernel buffer when the only two states we care about are
    # "contains 0 bytes" and "contains >= 1 byte". (It actually ends up being
    # 1 page = 4096 bytes.) This also makes buffer overflow a more common
    # condition, so we're more likely to notice if we break it.
    if sys.platform == "linux":
        F_SETPIPE_SZ = 1031
        fcntl.fcntl(fd, F_SETPIPE_SZ, 1)

class WakeupPipe:
    def __init__(self):
        self._read_fd, self._write_fd = os.pipe()
        maybe_shrink_pipe(self._read_fd)
        os.set_blocking(self._read_fd, False)
        os.set_blocking(self._write_fd, False)

    def wakeup_threadsafe(self):
        try:
            os.write(self._write_fd, b"\x00")
        except BlockingIOError:
            pass

    async def wait_woken(self):
        await _core.wait_readable(self._read_fd)
        # Drain the pipe:
        try:
            while True:
                os.read(self._read_fd, 2 ** 16)
        except BlockingIOError:
            pass

    def close(self):
        os.close(self._read_fd)
        os.close(self._write_fd)

################################################################

if hasattr(select, "epoll"):

    @attr.s(frozen=True)
    class _EpollStatistics:
        tasks_waiting_read = attr.ib()
        tasks_waiting_write = attr.ib()
        backend = attr.ib(default="epoll")

    @attr.s(slots=True, cmp=False, hash=False)
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
            # XX not sure if EPOLLEXCLUSIVE is actually safe... I think
            # probably we should use it here unconditionally, but:
            # https://stackoverflow.com/questions/41582560/how-does-epolls-epollexclusive-mode-interact-with-level-triggering
            #flags |= select.EPOLLEXCLUSIVE
            # We used to use ONESHOT here also, but it turns out that it's
            # confusing/complicated: you can't use ONESHOT+EPOLLEXCLUSIVE
            # together, you ONESHOT doesn't delete the registration but just
            # "disables" it so you re-enable with CTL rather than ADD (or
            # something?)...
            # https://lkml.org/lkml/2016/2/4/541
            return flags

    @attr.s(slots=True, cmp=False, hash=False)
    class EpollIOManager:
        _epoll = attr.ib(default=attr.Factory(select.epoll))
        # {fd: EpollWaiters}
        _registered = attr.ib(default=attr.Factory(dict))

        def statistics(self):
            tasks_waiting_read = 0
            tasks_waiting_write = 0
            for waiter in self._registered.values():
                if waiter.read_task is not None:
                    tasks_waiting_read += 1
                if waiter.write_task is not None:
                    tasks_waiting_write += 1
            return _EpollStatistics(
                tasks_waiting_read=tasks_waiting_read,
                tasks_waiting_write=tasks_waiting_write,
            )

        # Delegate wakeup functionality to WakeupPipe
        _wakeup = attr.ib(default=attr.Factory(WakeupPipe))
        def wakeup_threadsafe(self):
            self._wakeup.wakeup_threadsafe()
        async def wait_woken(self):
            await self._wakeup.wait_woken()

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
                self._update_registrations(fd, True)

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

        async def _epoll_wait(self, fd, attr_name):
            # KeyboardInterrupt here could corrupt self._registered
            locals()[LOCALS_KEY_KEYBOARD_INTERRUPT_SAFE] = False

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
            def abort():
                setattr(self._registered[fd], attr_name, None)
                self._update_registrations(fd, True)
                return _core.Abort.SUCCEEDED
            await _core.yield_indefinitely(abort)

        @_public
        @_hazmat
        async def wait_readable(self, fd):
            await self._epoll_wait(fd, "read_task")

        @_public
        @_hazmat
        async def wait_writable(self, fd):
            await self._epoll_wait(fd, "write_task")

################################################################

if hasattr(select, "kqueue"):

    @attr.s(frozen=True)
    class _KqueueStatistics:
        tasks_waiting = attr.ib()
        monitors = attr.ib()
        backend = attr.ib(default="kqueue")

    @attr.s(slots=True, cmp=False, hash=False)
    class KqueueIOManager:
        _kqueue = attr.ib(default=attr.Factory(select.kqueue))
        # {(ident, filter): Task or UnboundedQueue}
        _registered = attr.ib(default=attr.Factory(dict))

        def statistics(self):
            tasks_waiting = 0
            monitors = 0
            for receiver in self._registered.values():
                if type(receiver) is _core.Task:
                    tasks_waiting += 1
                else:
                    monitors += 1
            return _KqueueStatistics(
                tasks_waiting=tasks_waiting,
                monitors=monitors,
            )

        # Delegate wakeup functionality to WakeupPipe
        _wakeup = attr.ib(default=attr.Factory(WakeupPipe))
        def wakeup_threadsafe(self):
            self._wakeup.wakeup_threadsafe()
        async def wait_woken(self):
            await self._wakeup.wait_woken()

        def close(self):
            self._kqueue.close()
            self._wakeup.close()

        def handle_io(self, timeout):
            # max_events must be > 0 or kqueue gets cranky
            # and we generally want this to be strictly larger than the actual
            # number of events we get, so that we can tell that we've gotten
            # all the events in just 1 call.
            max_events = len(self._registered) + 1
            events = []
            while True:
                batch = self._kqueue.control([], max_events, timeout)
                events += batch
                if len(batch) < max_events:
                    break
                else:
                    timeout = 0
                    # and loop back to the start
            for event in events:
                key = (event.ident, event.filter)
                receiver = self._registered[key]
                if event.flags & select.KQ_EV_ONESHOT:
                    del self._registered[key]
                if type(receiver) is _core.Task:
                    _core.reschedule(receiver, _core.Value(event))
                else:
                    receiver.put_nowait(event)

        # kevent registration is complicated -- e.g. aio submission can
        # implicitly perform a EV_ADD, and EVFILT_PROC with NOTE_TRACK will
        # automatically register filters for child processes. So our lowlevel
        # API is *very* low-level: we expose the kqueue itself for adding
        # events or sticking into AIO submission structs, and split waiting
        # off into separate methods. It's your responsibility to make sure
        # that handle_io never receives an event without a corresponding
        # registration! This may be challenging if you want to be careful
        # about e.g. KeyboardInterrupt. Possibly this API could be improved to
        # be more ergonomic...

        @_public
        @_hazmat
        def current_kqueue(self):
            return self._kqueue

        @_public
        @_hazmat
        @contextmanager
        def kevent_monitor(self, ident, filter):
            key = (ident, filter)
            if key in self._registered:
                raise ValueError(
                    "attempt to register multiple listeners for same "
                    "ident/filter pair")
            q = _core.UnboundedQueue()
            self._registered[key] = q
            try:
                yield q
            finally:
                del self._registered[key]

        @_public
        @_hazmat
        async def wait_kevent(self, ident, filter, abort_func):
            key = (ident, filter)
            if key in self._registered:
                raise ValueError(
                    "attempt to register multiple listeners for same "
                    "ident/filter pair")
            self._registered[key] = _core.current_task()
            def abort():
                r = abort_func()
                if r is _core.Abort.SUCCEEDED:
                    del self._registered[key]
                return r
            return await _core.yield_indefinitely(abort)

        async def _wait_common(self, fd, filter):
            if not isinstance(fd, int):
                fd = fd.fileno()
            flags = select.KQ_EV_ADD | select.KQ_EV_ONESHOT
            event = select.kevent(fd, filter, flags)
            self._kqueue.control([event], 0)
            def abort():
                event = select.kevent(fd, filter, select.KQ_EV_DELETE)
                self._kqueue.control([event], 0)
                return _core.Abort.SUCCEEDED
            await self.wait_kevent(fd, filter, abort)

        @_public
        @_hazmat
        async def wait_readable(self, fd):
            await self._wait_common(fd, select.KQ_FILTER_READ)

        @_public
        @_hazmat
        async def wait_writable(self, fd):
            await self._wait_common(fd, select.KQ_FILTER_WRITE)
