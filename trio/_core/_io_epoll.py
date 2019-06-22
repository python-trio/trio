import select
import attr
import outcome

from .. import _core
from ._run import _public


@attr.s(slots=True, cmp=False, frozen=True)
class _EpollStatistics:
    tasks_waiting_read = attr.ib()
    tasks_waiting_write = attr.ib()
    backend = attr.ib(default="epoll")


@attr.s(slots=True, cmp=False)
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

        # flags |= select.EPOLLEXCLUSIVE
        # We used to use ONESHOT here also, but it turns out that it's
        # confusing/complicated: you can't use ONESHOT+EPOLLEXCLUSIVE
        # together, you ONESHOT doesn't delete the registration but just
        # "disables" it so you re-enable with CTL rather than ADD (or
        # something?)...
        # https://lkml.org/lkml/2016/2/4/541
        return flags


@attr.s(slots=True, cmp=False, hash=False)
class EpollIOManager:
    _epoll = attr.ib(factory=select.epoll)
    # {fd: EpollWaiters}
    _registered = attr.ib(factory=dict)

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

    def close(self):
        self._epoll.close()

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
            assert currently_registered
            del self._registered[fd]
            self._epoll.unregister(fd)
        else:
            if currently_registered:
                self._epoll.modify(fd, flags)
            else:
                self._epoll.register(fd, flags)

    # Public (hazmat) API:

    async def _epoll_wait(self, fd, attr_name):
        if not isinstance(fd, int):
            fd = fd.fileno()
        currently_registered = (fd in self._registered)
        if not currently_registered:
            self._registered[fd] = EpollWaiters()
        waiters = self._registered[fd]
        if getattr(waiters, attr_name) is not None:
            raise _core.BusyResourceError(
                "another task is already reading / writing this fd"
            )
        setattr(waiters, attr_name, _core.current_task())
        self._update_registrations(fd, currently_registered)

        def abort(_):
            setattr(self._registered[fd], attr_name, None)
            self._update_registrations(fd, True)
            return _core.Abort.SUCCEEDED

        await _core.wait_task_rescheduled(abort)

    @_public
    async def wait_readable(self, fd):
        await self._epoll_wait(fd, "read_task")

    @_public
    async def wait_writable(self, fd):
        await self._epoll_wait(fd, "write_task")

    @_public
    def notify_closing(self, fd):
        if not isinstance(fd, int):
            fd = fd.fileno()
        if fd not in self._registered:
            return

        waiters = self._registered[fd]

        def interrupt(task):
            exc = _core.ClosedResourceError("another task closed this fd")
            _core.reschedule(task, outcome.Error(exc))

        if waiters.write_task is not None:
            interrupt(waiters.write_task)
            waiters.write_task = None

        if waiters.read_task is not None:
            interrupt(waiters.read_task)
            waiters.read_task = None

        self._update_registrations(fd, True)
