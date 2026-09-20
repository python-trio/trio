from __future__ import annotations

import errno
import select
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING, Literal, TypeAlias

import attrs
import outcome

from .. import _core
from .._deprecate import warn_deprecated
from ._run import _public
from ._wakeup_socketpair import WakeupSocketpair

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from .._core import Abort, RaiseCancelT, Task, UnboundedQueue
    from .._file_io import _HasFileNo

assert not TYPE_CHECKING or (sys.platform != "linux" and sys.platform != "win32")

EventResult: TypeAlias = "list[select.kevent]"


@attrs.frozen(eq=False)
class _KqueueStatistics:
    tasks_waiting: int
    monitors: int
    backend: Literal["kqueue"] = attrs.field(init=False, default="kqueue")


@attrs.define(eq=False)
class KqueueIOManager:
    _kqueue: select.kqueue = attrs.Factory(select.kqueue)
    # {(ident, filter): Task or UnboundedQueue}
    _registered: dict[tuple[int, int], Task | UnboundedQueue[select.kevent]] = (
        attrs.Factory(dict)
    )
    _force_wakeup: WakeupSocketpair = attrs.Factory(WakeupSocketpair)
    _force_wakeup_fd: int | None = None

    def __attrs_post_init__(self) -> None:
        force_wakeup_event = select.kevent(
            self._force_wakeup.wakeup_sock,
            select.KQ_FILTER_READ,
            select.KQ_EV_ADD,
        )
        self._kqueue.control([force_wakeup_event], 0)
        self._force_wakeup_fd = self._force_wakeup.wakeup_sock.fileno()

    def statistics(self) -> _KqueueStatistics:
        tasks_waiting = 0
        monitors = 0
        for receiver in self._registered.values():
            if type(receiver) is _core.Task:
                tasks_waiting += 1
            else:
                monitors += 1
        return _KqueueStatistics(tasks_waiting=tasks_waiting, monitors=monitors)

    def close(self) -> None:
        self._kqueue.close()
        self._force_wakeup.close()

    def force_wakeup(self) -> None:
        self._force_wakeup.wakeup_thread_and_signal_safe()

    def get_events(self, timeout: float) -> EventResult:
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
            else:  # TODO: test this line
                timeout = 0
                # and loop back to the start
        return events

    def process_events(self, events: EventResult) -> None:
        for event in events:
            key = (event.ident, event.filter)
            if event.ident == self._force_wakeup_fd:
                self._force_wakeup.drain()
                continue
            receiver = self._registered.get(key)
            if receiver is None:
                # In guest mode, host callbacks can run between get_events()
                # and process_events(). If one cancels a wait that has already
                # completed then it will remove the receiver from _registered,
                # so it will be missing when we get here; we can just drop it.
                continue
            if event.flags & select.KQ_EV_ONESHOT:  # TODO: test this branch
                del self._registered[key]
            if isinstance(receiver, _core.Task):
                _core.reschedule(receiver, outcome.Value(event))
            else:
                receiver.put_nowait(event)  # TODO: test this line

    # kevent registration is complicated -- e.g. aio submission can
    # implicitly perform an EV_ADD, and EVFILT_PROC with NOTE_TRACK will
    # automatically register filters for child processes. Earlier revisions
    # had a *very* low-level API, where the caller had responsibility for
    # registering events with the OS kqueue. wait_kevent now takes care of
    # that for one-shot waits. monitor_kevent has not yet been updated
    # similarly, so its callers still need to register events themselves.

    @_public
    def current_kqueue(self) -> select.kqueue:
        """TODO: these are implemented, but are currently more of a sketch than
        anything real. See `#26
        <https://github.com/python-trio/trio/issues/26>`__.
        """
        return self._kqueue

    @contextmanager
    @_public
    def monitor_kevent(
        self,
        ident: int,
        filter: int,
    ) -> Iterator[_core.UnboundedQueue[select.kevent]]:
        """TODO: these are implemented, but are currently more of a sketch than
        anything real. See `#26
        <https://github.com/python-trio/trio/issues/26>`__.
        """
        key = (ident, filter)
        if key in self._registered:
            raise _core.BusyResourceError(
                "attempt to register multiple listeners for same ident/filter pair",
            )
        q = _core.UnboundedQueue[select.kevent]()
        self._registered[key] = q
        try:
            yield q
        finally:
            del self._registered[key]

    @_public
    async def wait_kevent(
        self,
        ident: int | _HasFileNo,
        filter: int,
        abort_func: Callable[[RaiseCancelT], Abort] | None = None,
        *,
        fflags: int = 0,
        data: int = 0,
    ) -> select.kevent:
        """Waits for a one-shot kevent to happen.

        This is a low-level function that lets you wait on a specific kevent,
        in case you have a use case not covered by the IO primitives in Trio.

        This registers ``kevent(ident, filter, flags, fflags, data)``, where
        ``flags`` is set to ``select.KQ_EV_ADD | select.KQ_EV_ONESHOT``, and
        waits for it to complete. If cancelled then it is removed with ``flags``
        set to ``select.KQ_EV_DELETE``.

        Args:
            ident: Value used to identify the event. The interpretation depends
                on the filter but it's usually the file descriptor.
            filter: Name of the kernel filter e.g. ``select.KQ_FILTER_READ``.
            fflags: Filter-specific flags.
            data: Filter-specific data.

        Returns:
            select.kevent: The event returned from kqueue.

        Raises:
            BusyResourceError: if another task is waiting for this
                ``(ident, filter)`` pair.
            OSError: if the kqueue rejects the registration (for example,
                `ProcessLookupError` for an ``EVFILT_PROC`` ident that has
                already exited).
        """
        if not isinstance(ident, int):
            ident = ident.fileno()

        if abort_func is not None:
            warn_deprecated(
                "wait_kevent(..., abort_func=...)",
                "0.35.0",
                issue=578,
                instead="wait_kevent(ident, filter, fflags=..., data=...),"
                " which registers the kevent itself",
            )

        key = (ident, filter)
        if key in self._registered:
            raise _core.BusyResourceError(
                "attempt to register multiple listeners for same ident/filter pair",
            )

        if abort_func is not None:
            abort_fn = abort_func
            self._registered[key] = _core.current_task()

            def abort_deprecated(raise_cancel: RaiseCancelT) -> Abort:
                r = abort_fn(raise_cancel)
                if r is _core.Abort.SUCCEEDED:
                    del self._registered[key]
                return r

            # wait_task_rescheduled does not have its return type typed
            return await _core.wait_task_rescheduled(  # type: ignore[no-any-return]
                abort_deprecated,
            )

        # Register the event before updating _registered in case this throws
        event = select.kevent(
            ident,
            filter,
            select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
            fflags,
            data,
        )
        self._kqueue.control([event], 0)
        self._registered[key] = _core.current_task()

        def abort(raise_cancel: RaiseCancelT) -> Abort:
            del self._registered[key]
            try:
                event = select.kevent(ident, filter, select.KQ_EV_DELETE)
                self._kqueue.control([event], 0)
            except OSError as exc:
                # kqueue tracks individual fds (*not* the underlying file
                # object, see _io_epoll.py for a long discussion of why this
                # distinction matters), and automatically deregisters an event
                # if the fd is closed. So if kqueue.control says that it
                # doesn't know about this event, it could be because
                # the fd was closed behind our backs. (Too bad we can't ask it
                # to wake us up when this happens, versus discovering it after
                # the fact... oh well, you can't have everything.)
                # FreeBSD reports this using EBADF. macOS uses ENOENT.
                #
                # This can also happen if, in guest mode, the cancellation
                # happens just after the event was fetched by get_events()
                # (which removes it, since it's oneshot) but before it has been
                # processed it in process_events(). This is reported as
                # errno.ENOENT on both platforms.
                if exc.errno in (errno.EBADF, errno.ENOENT):  # pragma: no branch
                    pass
                else:  # pragma: no cover
                    # As far as we know, this branch can't happen.
                    raise
            return _core.Abort.SUCCEEDED

        # wait_task_rescheduled does not have its return type typed
        return await _core.wait_task_rescheduled(abort)  # type: ignore[no-any-return]

    @_public
    async def wait_readable(self, fd: int | _HasFileNo) -> None:
        """Block until the kernel reports that the given object is readable.

        On Unix systems, ``fd`` must either be an integer file descriptor,
        or else an object with a ``.fileno()`` method which returns an
        integer file descriptor. Any kind of file descriptor can be passed,
        though the exact semantics will depend on your kernel. For example,
        this probably won't do anything useful for on-disk files.

        On Windows systems, ``fd`` must either be an integer ``SOCKET``
        handle, or else an object with a ``.fileno()`` method which returns
        an integer ``SOCKET`` handle. File descriptors aren't supported,
        and neither are handles that refer to anything besides a
        ``SOCKET``.

        :raises trio.BusyResourceError:
            if another task is already waiting for the given socket to
            become readable.
        :raises trio.ClosedResourceError:
            if another task calls :func:`notify_closing` while this
            function is still working.
        """
        await self.wait_kevent(fd, select.KQ_FILTER_READ)

    @_public
    async def wait_writable(self, fd: int | _HasFileNo) -> None:
        """Block until the kernel reports that the given object is writable.

        See `wait_readable` for the definition of ``fd``.

        :raises trio.BusyResourceError:
            if another task is already waiting for the given socket to
            become writable.
        :raises trio.ClosedResourceError:
            if another task calls :func:`notify_closing` while this
            function is still working.
        """
        await self.wait_kevent(fd, select.KQ_FILTER_WRITE)

    @_public
    def notify_closing(self, fd: int | _HasFileNo) -> None:
        """Notify waiters of the given object that it will be closed.

        Call this before closing a file descriptor (on Unix) or socket (on
        Windows). This will cause any `wait_readable` or `wait_writable`
        calls on the given object to immediately wake up and raise
        `~trio.ClosedResourceError`.

        This doesn't actually close the object – you still have to do that
        yourself afterwards. Also, you want to be careful to make sure no
        new tasks start waiting on the object in between when you call this
        and when it's actually closed. So to close something properly, you
        usually want to do these steps in order:

        1. Explicitly mark the object as closed, so that any new attempts
           to use it will abort before they start.
        2. Call `notify_closing` to wake up any already-existing users.
        3. Actually close the object.

        It's also possible to do them in a different order if that's more
        convenient, *but only if* you make sure not to have any checkpoints in
        between the steps. This way they all happen in a single atomic
        step, so other tasks won't be able to tell what order they happened
        in anyway.
        """
        if not isinstance(fd, int):
            fd = fd.fileno()

        for filter_ in [select.KQ_FILTER_READ, select.KQ_FILTER_WRITE]:
            key = (fd, filter_)
            receiver = self._registered.get(key)

            if receiver is None:
                continue

            if type(receiver) is _core.Task:
                event = select.kevent(fd, filter_, select.KQ_EV_DELETE)
                try:
                    self._kqueue.control([event], 0)
                except OSError as e:
                    if e.errno in (errno.EBADF, errno.ENOENT):  # pragma: no branch
                        # the event isn't in kqueue
                        continue
                    raise  # pragma: no cover
                exc = _core.ClosedResourceError("another task closed this fd")
                _core.reschedule(receiver, outcome.Error(exc))
                del self._registered[key]
            else:
                # XX this is an interesting example of a case where being able
                # to close a queue would be useful...
                raise NotImplementedError(
                    "can't close an fd that monitor_kevent is using",
                )
