import select
import attr
import outcome
import copy
from collections import defaultdict

from .. import _core
from ._run import _public


@attr.s(slots=True, eq=False, frozen=True)
class _EpollStatistics:
    tasks_waiting_read = attr.ib()
    tasks_waiting_write = attr.ib()
    backend = attr.ib(default="epoll")

# Some facts about epoll
# ----------------------
#
# Internally, an epoll object is sort of like a WeakKeyDictionary where the
# keys are tuples of (fd number, file object). When you call epoll_ctl, you
# pass in an fd; that gets converted to an (fd number, file object) tuple by
# looking up the fd in the process's fd table at the time of the call. When an
# event happens on the file object, epoll_wait drops the file object part, and
# just returns the fd number in its event. So from the outside it looks like
# it's keeping a table of fds, but really it's a bit more complicated. This
# has some subtle consequences.
#
# In general, file objects inside the kernel are reference counted. Each entry
# in a process's fd table holds a reference to the file objects, and most
# operations that use file objects take a temporary reference while they're
# working. So when you call close() on an fd, that might or might not cause
# the file object to be deallocated -- it depends on whether there are any
# other fds referring to that file object. Some common ways this can happen:
#
# - after calling dup(), you have two fds in the same process referring to the
#   same file object. Even if you close one, the file object will be kept
#   alive by the other.
# - when calling fork(), the child inherits a copy of the parent's fd table,
#   so all the file objects get another reference. (But if the fork() is
#   followed by exec(), then all of the child's fds that have the CLOEXEC flag
#   set will be closed at that point.)
# - most syscalls that work on fds take a reference to the underlying file
#   object while they're running. So e.g. if there's a thread blocked in
#   read(fd), and then another thread calls close(fd), the underlying file
#   object won't actually be closed until after read() returns.
#
# However, epoll does *not* take a reference to the file objects in its set
# (that's what makes it similar to a WeakKeyDictionary). File objects inside
# an epoll interest set will be deallocated if all *other* references to them
# are closed, and then the epoll object will automatically deregister that
# file object and stop reporting events on it. So that's quite handy.
#
# But, what happens if we do:
#
#   fd1 = open(...)
#   epoll_ctl(EPOLL_CTL_ADD, fd1, ...)
#   fd2 = dup(fd1)
#   close(fd1)
#
# ? In this case, the dup() keeps the underlying file object alive, so it
# remains registered in the epoll object's interest set, as the tuple (fd1,
# file object). But, fd1 no longer refers to this file object! You might think
# there was some magic to handle this, but unfortunately no; the consequences
# are totally predictable from what I said above:
#
# If any events occur on the file object, then epoll will report them as
# happening on fd1, even though that doesn't make sense.
#
# So perhaps we would like to deregister fd1 to stop getting events. But how?
# When we call epoll_ctl, we have to pass an fd number, which will get
# expanded to an (fd number, file object) tuple. We can't pass fd1, because
# when epoll_ctl tries to look it up, it won't find our file object. And we
# can't pass fd2, because that will get expanded to (fd2, file object), which
# is a different lookup key. In fact, in this case it is *impossible* to
# de-register this fd!
#
# It is even possible that fd1 will get assigned to another file object, and
# then we can have multiple keys registered simultaneously using the same fd
# number, like: (fd1, file object 1), (fd1, file object 2)
# epoll will happily report events on either file object as having happened on
# "fd1".
#
# And what makes this particularly nasty is that suppose the old file object
# becomes, say, readable. That means that every time we call epoll_wait, it
# will return immediately to tell us that "fd1" is readable. Normally, we
# would handle this by de-registering fd1, waking up wait_readable, then the
# user will call read() or recv() or something, etc., so it's fine. But if
# this happens on a stale fd where we can't remove the registration, then we
# might get stuck in a state where epoll_ctl *always* returns immediately, so
# our event loop becomes unable to sleep, and now our program is burning 100%
# of the CPU doing nothing.
#
#
# What does this mean for Trio?
# -----------------------------
#
# Since we don't control the user's code, we have no way to guarantee that we
# don't get stuck in the pathological situation described above. For example,
# a user could call wait_readable(fd) in one task, and then while that's
# running, they might close(fd) from another task. In this situation, they're
# *supposed* to call notify_closing(fd) to let us know what's happening, so we
# can interrupt the wait_readable() call and avoid getting into this mess. And
# that's the only thing that can possibly work correctly in all cases. But
# sometimes code has bugs. So we would like to be able to at least survive
# this without corrupting Trio's internal state or otherwise causing the whole
# program to explode messily.
#
# Our solution: we always use EPOLLONESHOT when registering an fd with epoll.
# This way, we might get *one* spurious event on a stale fd, but then epoll
# will automatically quiet it until we explicitly say that we want more
# events... which on a stale fd we can't do, so that will never happen, and we
# avoid getting stuck in a busy-loop. And this might even cause some wait_*
# function to return before it should have... but in general, the wait_*
# functions are allowed to have some spurious wakeups; the user code will just
# attempt the operation, get EWOULDBLOCK, and call wait_* again.
#
# (We could also get a spurious BusyResourceError, but at least that doesn't
# corrupt the whole program.)
#
# As a bonus, EPOLLONESHOT also saves us having to explicitly deregister fds,
# so it's a bit more efficient in the normal case too.
#
# However, EPOLLONESHOT has a few trade-offs:
#
# First, you can't combine EPOLLONESHOT with EPOLLEXCLUSIVE. This is a bit sad
# in one somewhat rare case: if you have a multi-process server where a group
# of processes all share the same listening socket, then EPOLLEXCLUSIVE can be
# used to avoid "thundering herd" problems when a new connection comes in. But
# this isn't too bad. It's not clear if EPOLLEXCLUSIVE even works here anyway:
#
#   https://stackoverflow.com/questions/41582560/how-does-epolls-epollexclusive-mode-interact-with-level-triggering
#
# And if we really need to support this, we could always add support through
# some specialized API in the future.
#
# Second, EPOLLONESHOT does not actually *deregister* the fd after delivering
# an event (EPOLL_CTL_DEL). Instead, it keeps the fd registered, but
# effectively does an EPOLL_CTL_MOD to set the fd's interest flags to
# all-zeros.
#
# So one possible problem would be that the epoll object will end up keeping
# the underlying file object alive. Fortunately, that doesn't happen, as
# described above – if we have a stale fd that's been silenced by
# EPOLLONESHOT, then I guess it wastes a bit of kernel memory remembering this
# fd that can never be revived, but when the underlying file object is
# eventually closed, that memory will be reclaimed. So that's OK.
#
# The other issue is that when someon calls wait_*, using EPOLLONESHOT means
# that if we have ever waited for this fd before, we have to use EPOLL_CTL_MOD
# to re-enable it; but if it's a new fd, we have to use EPOLL_CTL_ADD. How do
# we know which to use? There's no reasonable way to track which fds are
# currently registered -- remember, we're assuming the user might have gone
# and rearranged their fds without telling us!
#
# Fortunately, this also has a simple solution: usually, if we wait on a
# socket or other fd once, we will probably wait lots of times. And the epoll
# object itself knows which fds it already has registered. So when an fd comes
# in, we optimistically assume that it's been waited on before, and try doing
# EPOLL_CTL_MOD. If that failed with an ENOENT error, then we try again with
# EPOLL_CTL_ADD.
#
# So that's why this code is the way it is. And now you know more than you
# wanted to about how epoll works.


@attr.s(slots=True, eq=False)
class EpollWaiters:
    read_task = attr.ib(default=None)
    write_task = attr.ib(default=None)
    current_flags = attr.ib(default=0)

    def wake_all(self, exc):
        try:
            current_task = _core.current_task()
        except RuntimeError:
            current_task = None
        raise_at_end = False
        for attr_name in ["read_task", "write_task"]:
            task = getattr(self, attr_name)
            if task is not None:
                if task is current_task:
                    raise_at_end = True
                else:
                    _core.reschedule(task, outcome.Error(copy.copy(exc)))
                setattr(self, attr_name, None)
        if raise_at_end:
            raise exc


@attr.s(slots=True, eq=False, hash=False)
class EpollIOManager:
    _epoll = attr.ib(factory=select.epoll)
    # {fd: EpollWaiters}
    _registered = attr.ib(factory=lambda: defaultdict(EpollWaiters))

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
            # EPOLLONESHOT always clears the flags
            waiters.current_flags = 0
            # Clever hack stolen from selectors.EpollSelector: an event
            # with EPOLLHUP or EPOLLERR flags wakes both readers and
            # writers.
            if flags & ~select.EPOLLIN and waiters.write_task is not None:
                _core.reschedule(waiters.write_task)
                waiters.write_task = None
            if flags & ~select.EPOLLOUT and waiters.read_task is not None:
                _core.reschedule(waiters.read_task)
                waiters.read_task = None
            self._update_registrations(fd)

    def _update_registrations(self, fd):
        waiters = self._registered[fd]
        wanted_flags = 0
        if waiters.read_task is not None:
            wanted_flags |= select.EPOLLIN
        if waiters.write_task is not None:
            wanted_flags |= select.EPOLLOUT
        if wanted_flags != waiters.current_flags:
            try:
                try:
                    # First try EPOLL_CTL_MOD
                    self._epoll.modify(fd, wanted_flags | select.EPOLLONESHOT)
                except OSError:
                    # If that fails, it might be a new fd; try EPOLL_CTL_ADD
                    self._epoll.register(fd, wanted_flags | select.EPOLLONESHOT)
                waiters.current_flags = wanted_flags
            except OSError as exc:
                # If everything fails, probably it's a bad fd, e.g. because
                # the fd was closed behind our back. In this case we don't
                # want to try to unregister the fd, because that will probably
                # fail too. Just clear our state and wake everyone up.
                del self._registered[fd]
                # This could raise (in case we're calling this inside one of
                # the to-be-woken tasks), so we have to do it last.
                waiters.wake_all(exc)
                return
        if not wanted_flags:
            del self._registered[fd]

    async def _epoll_wait(self, fd, attr_name):
        if not isinstance(fd, int):
            fd = fd.fileno()
        waiters = self._registered[fd]
        if getattr(waiters, attr_name) is not None:
            raise _core.BusyResourceError(
                "another task is already reading / writing this fd"
            )
        setattr(waiters, attr_name, _core.current_task())
        self._update_registrations(fd)

        def abort(_):
            setattr(waiters, attr_name, None)
            self._update_registrations(fd)
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
        self._registered[fd].wake_all(
            _core.ClosedResourceError("another task closed this fd")
        )
        del self._registered[fd]
        try:
            self._epoll.unregister(fd)
        except (OSError, ValueError):
            pass
