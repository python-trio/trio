import itertools
from contextlib import contextmanager
import enum

import outcome
import attr

from .. import _core
from ._run import _public

from ._windows_cffi import (
    ffi,
    kernel32,
    ntdll,
    ws2_32,
    INVALID_HANDLE_VALUE,
    raise_winerror,
    _handle,
    ErrorCodes,
    FileFlags,
    AFDPollFlags,
    WSAIoctls,
    CompletionModes,
    IoControlCodes,
)

# There's a lot to be said about the overall design of a Windows event
# loop. See
#
#    https://github.com/python-trio/trio/issues/52
#
# for discussion. This now just has some lower-level notes:
#
# How IOCP fits together:
# - each notification event (OVERLAPPED_ENTRY) contains:
#   - the "completion key" (an integer)
#   - pointer to OVERLAPPED
#   - dwNumberOfBytesTransferred
# - and in addition, for regular I/O, the OVERLAPPED structure gets filled in
#   with:
#   - result code (named "Internal")
#   - number of bytes transferred (named "InternalHigh"); redundant with
#     dwNumberOfBytesTransferred *if* this is a regular I/O event.
#
# There are also some other entries in OVERLAPPED which only matter on input:
# - Offset and OffsetHigh which are inputs to {Read,Write}File and
#   otherwise always zero
# - hEvent which is for if you aren't using IOCP; we always set it to zero.
#
# PostQueuedCompletionStatus: lets you set the 3 magic scalars to whatever you
# want.
#
# Regular I/O events: these are identified by the pointer-to-OVERLAPPED. The
# "completion key" is a property of a particular handle being operated on that
# is set when associating the handle with the IOCP. We don't use it, so should
# always set it to zero.
#
# Socket state notifications: the public APIs that windows provides for this
# are all really awkward and don't integrate with IOCP. So we drop down to a
# lower level, and talk directly to the socket device driver in the kernel,
# which is called "AFD". The magic IOCTL_AFD_POLL operation lets us request a
# regular IOCP notification when a given socket enters a given state, which is
# exactly what we want. Unfortunately, this is a totally undocumented internal
# API. Fortunately libuv also does this, so we can be pretty confident that MS
# won't break it on us, and there is a *little* bit of information out there
# if you go digging.
#
# Job notifications: effectively uses PostQueuedCompletionStatus, the
# "completion key" is used to identify which job we're talking about, and the
# other two scalars are overloaded to contain arbitrary data.
#
# So our strategy is:
# - when binding handles to the IOCP, we always set the completion key to 0.
#   when dispatching received events, when the completion key is 0 we dispatch
#   based on lpOverlapped
# - when we try to cancel an I/O operation and the cancellation fails,
#   we post a completion with completion key 1; if this arrives before the
#   real completion (with completion key 0) we assume the user forgot to
#   call register_with_iocp on their handle, and raise an error accordingly
#   (without this logic we'd hang forever uninterruptibly waiting for the
#   completion that never arrives)
# - other completion keys are available for user use


# The completion keys we use
class CKeys(enum.IntEnum):
    AFD_POLL = 0
    WAIT_OVERLAPPED = 1
    LATE_CANCEL = 2
    USER_DEFINED = 3  # and above


def reprO(lpOverlapped):
    return hex(int(ffi.cast("uintptr_t", lpOverlapped)))
    #return repr(ffi.cast("void *", lpOverlapped))


def _check(success):
    if not success:
        raise_winerror()
    return success


def _get_base_socket(sock):
    if hasattr(sock, "fileno"):
        sock = sock.fileno()
    base_ptr = ffi.new("HANDLE *")
    out_size = ffi.new("DWORD *")
    failed = ws2_32.WSAIoctl(
        ffi.cast("SOCKET", sock),
        WSAIoctls.SIO_BASE_HANDLE,
        ffi.NULL,
        0,
        base_ptr,
        ffi.sizeof("HANDLE"),
        out_size,
        ffi.NULL,
        ffi.NULL,
    )
    if failed:
        code = ws2_32.WSAGetLastError()
        raise_winerror(code)
    return base_ptr[0]


def _afd_helper_handle():
    # The "AFD" driver is exposed at the NT path "\Device\Afd". We're using
    # the Win32 CreateFile, though, so we have to pass a Win32 path. \\.\ is
    # how Win32 refers to the NT \GLOBAL??\ directory, and GLOBALROOT is a
    # symlink inside that directory that points to the root of the NT path
    # system. So by sticking that in front of the NT path, we get a Win32
    # path. Alternatively, we could use NtCreateFile directly, since it takes
    # an NT path. But we already wrap CreateFileW so this was easier.
    # References:
    #   https://blogs.msdn.microsoft.com/jeremykuhne/2016/05/02/dos-to-nt-a-paths-journey/
    #   https://stackoverflow.com/a/21704022
    rawname = r"\\.\GLOBALROOT\Device\Afd\Trio".encode("utf-16le") + b"\0\0"
    rawname_buf = ffi.from_buffer(rawname)

    handle = kernel32.CreateFileW(
        ffi.cast("LPCWSTR", rawname_buf),
        FileFlags.SYNCHRONIZE,
        FileFlags.FILE_SHARE_READ | FileFlags.FILE_SHARE_WRITE,
        ffi.NULL,  # no security attributes
        FileFlags.OPEN_EXISTING,
        FileFlags.FILE_FLAG_OVERLAPPED,
        ffi.NULL,  # no template file
    )
    if handle == INVALID_HANDLE_VALUE:  # pragma: no cover
        raise_winerror()
    return handle


# AFD_POLL has a finer-grained set of events than other APIs. We collapse them
# down into Unix-style "readable" and "writable".
#
# There's also a AFD_POLL_LOCAL_CLOSE that we could wait on, to potentially
# catch some cases where someone forgot to call notify_closing. But it's not
# reliable – e.g. if the socket has been dup'ed, then closing one of the
# handles doesn't trigger the event – and it's not available on Unix-like
# platforms. So it seems like including it here would be more likely to mask
# subtle bugs than to actually help anything.

READABLE_FLAGS = (
    AFDPollFlags.AFD_POLL_RECEIVE
    | AFDPollFlags.AFD_POLL_ACCEPT
    | AFDPollFlags.AFD_POLL_DISCONNECT  # other side sent an EOF
    | AFDPollFlags.AFD_POLL_ABORT
)

WRITABLE_FLAGS = (
    AFDPollFlags.AFD_POLL_SEND
    | AFDPollFlags.AFD_POLL_CONNECT_FAIL
    | AFDPollFlags.AFD_POLL_ABORT
)


# Annoyingly, while the API makes it *seem* like you can happily issue
# as many independent AFD_POLL operations as you want without them interfering
# with each other, in fact if you issue two AFD_POLL operations for the same
# socket at the same time, then Windows gets super confused. For example, if
# we issue one operation from wait_readable, and another independent operation
# from wait_writable, then Windows may complete the wait_writable operation
# when the socket becomes readable.
#
# To avoid this, we have to coalesce all the operations on a single socket
# into one, and when the set of waiters changes we have to throw away the old
# operation and start a new one.
@attr.s(slots=True, eq=False)
class AFDWaiters:
    read_task = attr.ib(default=None)
    write_task = attr.ib(default=None)
    current_op = attr.ib(default=None)


# We also need to bundle up all the info for a single op into a standalone
# object, because we need to keep all these objects alive until the operation
# finishes, even if we're throwing it away.
@attr.s(slots=True, eq=False, frozen=True)
class AFDPollOp:
    lpOverlapped = attr.ib()
    poll_info = attr.ib()
    waiters = attr.ib()


@attr.s(slots=True, eq=False, frozen=True)
class _WindowsStatistics:
    tasks_waiting_readable = attr.ib()
    tasks_waiting_writable = attr.ib()
    tasks_waiting_overlapped = attr.ib()
    completion_key_monitors = attr.ib()
    backend = attr.ib(default="windows")


# Maximum number of events to dequeue from the completion port on each pass
# through the run loop. Somewhat arbitrary. Should be large enough to collect
# a good set of tasks on each loop, but not so large to waste tons of memory.
# (Each WindowsIOManager holds a buffer whose size is ~32x this number.)
MAX_EVENTS = 1000


@attr.s(frozen=True)
class CompletionKeyEventInfo:
    lpOverlapped = attr.ib()
    dwNumberOfBytesTransferred = attr.ib()


class WindowsIOManager:
    def __init__(self):
        # If this method raises an exception, then __del__ could run on a
        # half-initialized object. So we initialize everything that __del__
        # touches to safe values up front, before we do anything that can
        # fail.
        self._iocp = None
        self._afd = None

        self._iocp = _check(
            kernel32.CreateIoCompletionPort(
                INVALID_HANDLE_VALUE, ffi.NULL, 0, 0
            )
        )
        self._events = ffi.new("OVERLAPPED_ENTRY[]", MAX_EVENTS)

        self._afd = _afd_helper_handle()
        self._register_with_iocp(self._afd, CKeys.AFD_POLL)
        # {lpOverlapped: AFDPollOp}
        self._afd_ops = {}
        # {socket handle: AFDWaiters}
        self._afd_waiters = {}

        # {lpOverlapped: task}
        self._overlapped_waiters = {}
        self._posted_too_late_to_cancel = set()

        self._completion_key_queues = {}
        self._completion_key_counter = itertools.count(CKeys.USER_DEFINED)

    def close(self):
        try:
            if self._iocp is not None:
                iocp = self._iocp
                self._iocp = None
                _check(kernel32.CloseHandle(iocp))
        finally:
            if self._afd is not None:
                afd = self._afd
                self._afd = None
                _check(kernel32.CloseHandle(afd))

    def __del__(self):
        self.close()

    def statistics(self):
        tasks_waiting_readable = 0
        tasks_waiting_writable = 0
        for waiter in self._afd_waiters.values():
            if waiter.read_task is not None:
                tasks_waiting_readable += 1
            if waiter.write_task is not None:
                tasks_waiting_writable += 1
        return _WindowsStatistics(
            tasks_waiting_readable=tasks_waiting_readable,
            tasks_waiting_writable=tasks_waiting_writable,
            tasks_waiting_overlapped=len(self._overlapped_waiters),
            completion_key_monitors=len(self._completion_key_queues),
        )

    def handle_io(self, timeout):
        received = ffi.new("PULONG")
        milliseconds = round(1000 * timeout)
        if timeout > 0 and milliseconds == 0:
            milliseconds = 1
        try:
            _check(
                kernel32.GetQueuedCompletionStatusEx(
                    self._iocp, self._events, MAX_EVENTS, received,
                    milliseconds, 0
                )
            )
        except OSError as exc:
            if exc.winerror == ErrorCodes.WAIT_TIMEOUT:
                return
            raise
        for i in range(received[0]):
            entry = self._events[i]
            if entry.lpCompletionKey == CKeys.AFD_POLL:
                print(f"AFD completion: {entry.lpOverlapped!r}")
                lpo = entry.lpOverlapped
                op = self._afd_ops.pop(lpo)
                waiters = op.waiters
                if waiters.current_op is not op:
                    # Stale op, nothing to do
                    print("stale, nothing to do")
                    pass
                else:
                    waiters.current_op = None
                    # I don't think this can happen, so if it does let's crash
                    # and get a debug trace.
                    if lpo.Internal != 0:  # pragma: no cover
                        code = ntdll.RtlNtStatusToDosError(lpo.Internal)
                        raise_winerror(code)
                    flags = op.poll_info.Handles[0].Events
                    print("flags: {AFDPollFlags(flags)!r}")
                    if waiters.read_task and flags & READABLE_FLAGS:
                        print("waking reader")
                        _core.reschedule(waiters.read_task)
                        waiters.read_task = None
                    if waiters.write_task and flags & WRITABLE_FLAGS:
                        print("waking writer")
                        _core.reschedule(waiters.write_task)
                        waiters.write_task = None
                    self._refresh_afd(op.poll_info.Handles[0].Handle)
            elif entry.lpCompletionKey == CKeys.WAIT_OVERLAPPED:
                # Regular I/O event, dispatch on lpOverlapped
                print(f"waking {reprO(entry.lpOverlapped)}")
                waiter = self._overlapped_waiters.pop(entry.lpOverlapped)
                _core.reschedule(waiter)
            elif entry.lpCompletionKey == CKeys.LATE_CANCEL:
                # Post made by a regular I/O event's abort_fn
                # after it failed to cancel the I/O. If we still
                # have a waiter with this lpOverlapped, we didn't
                # get the regular I/O completion and almost
                # certainly the user forgot to call
                # register_with_iocp.
                self._posted_too_late_to_cancel.remove(entry.lpOverlapped)
                try:
                    waiter = self._overlapped_waiters.pop(entry.lpOverlapped)
                except KeyError:
                    # Looks like the actual completion got here before this
                    # fallback post did -- we're in the "expected" case of
                    # too-late-to-cancel, where the user did nothing wrong.
                    # Nothing more to do.
                    pass
                else:
                    exc = _core.TrioInternalError(
                        "Failed to cancel overlapped I/O in {} and didn't "
                        "receive the completion either. Did you forget to "
                        "call register_with_iocp()?".format(waiter.name)
                    )
                    # Raising this out of handle_io ensures that
                    # the user will see our message even if some
                    # other task is in an uncancellable wait due
                    # to the same underlying forgot-to-register
                    # issue (if their CancelIoEx succeeds, we
                    # have no way of noticing that their completion
                    # won't arrive). Unfortunately it loses the
                    # task traceback. If you're debugging this
                    # error and can't tell where it's coming from,
                    # try changing this line to
                    # _core.reschedule(waiter, outcome.Error(exc))
                    raise exc
            else:
                # dispatch on lpCompletionKey
                queue = self._completion_key_queues[entry.lpCompletionKey]
                overlapped = int(ffi.cast("uintptr_t", entry.lpOverlapped))
                transferred = entry.dwNumberOfBytesTransferred
                info = CompletionKeyEventInfo(
                    lpOverlapped=overlapped,
                    dwNumberOfBytesTransferred=transferred,
                )
                queue.put_nowait(info)

    def _register_with_iocp(self, handle, completion_key):
        handle = _handle(handle)
        _check(
            kernel32.CreateIoCompletionPort(
                handle, self._iocp, completion_key, 0
            )
        )
        # Supposedly this makes things slightly faster, by disabling the
        # ability to do WaitForSingleObject(handle). We would never want to do
        # that anyway, so might as well get the extra speed (if any).
        # Ref: http://www.lenholgate.com/blog/2009/09/interesting-blog-posts-on-high-performance-servers.html
        _check(
            kernel32.SetFileCompletionNotificationModes(
                handle, CompletionModes.FILE_SKIP_SET_EVENT_ON_HANDLE
            )
        )

    ################################################################
    # AFD stuff
    ################################################################

    def _refresh_afd(self, base_handle):
        waiters = self._afd_waiters[base_handle]
        print(f"refreshing AFD for {base_handle!r}: {waiters!r}")
        if waiters.current_op is not None:
            try:
                _check(
                    kernel32.CancelIoEx(
                        self._afd, waiters.current_op.lpOverlapped
                    )
                )
            except OSError as exc:
                if exc.winerror != ErrorCodes.ERROR_NOT_FOUND:
                    raise
            waiters.current_op = None

        flags = 0
        if waiters.read_task is not None:
            flags |= READABLE_FLAGS
        if waiters.write_task is not None:
            flags |= WRITABLE_FLAGS

        if not flags:
            print("nothing to do; clearing")
            del self._afd_waiters[base_handle]
        else:
            lpOverlapped = ffi.new("LPOVERLAPPED")
            print(f"new AFD: {reprO(lpOverlapped)} for {flags!r} on {base_handle!r}")

            poll_info = ffi.new("AFD_POLL_INFO *")
            poll_info.Timeout = 2**63 - 1  # INT64_MAX
            poll_info.NumberOfHandles = 1
            poll_info.Exclusive = 0
            poll_info.Handles[0].Handle = base_handle
            poll_info.Handles[0].Status = 0
            poll_info.Handles[0].Events = flags

            try:
                _check(
                    kernel32.DeviceIoControl(
                        self._afd,
                        IoControlCodes.IOCTL_AFD_POLL,
                        poll_info,
                        ffi.sizeof("AFD_POLL_INFO"),
                        poll_info,
                        ffi.sizeof("AFD_POLL_INFO"),
                        ffi.NULL,
                        lpOverlapped,
                    )
                )
            except OSError as exc:
                if exc.winerror != ErrorCodes.ERROR_IO_PENDING:
                    raise

            op = AFDPollOp(lpOverlapped, poll_info, waiters)
            waiters.current_op = op
            self._afd_ops[lpOverlapped] = op

    async def _afd_poll(self, sock, mode):
        base_handle = _get_base_socket(sock)
        waiters = self._afd_waiters.get(base_handle)
        if waiters is None:
            waiters = AFDWaiters()
            self._afd_waiters[base_handle] = waiters
        if getattr(waiters, mode) is not None:
            raise _core.BusyResourceError
        setattr(waiters, mode, _core.current_task())
        self._refresh_afd(base_handle)

        def abort_fn(_):
            print(f"_afd_poll({base_handle!r}, {mode!r}) cancelled")
            setattr(waiters, mode, None)
            self._refresh_afd(base_handle)
            return _core.Abort.SUCCEEDED

        await _core.wait_task_rescheduled(abort_fn)

    @_public
    async def wait_readable(self, sock):
        print("wait_readable start")
        try:
            await self._afd_poll(sock, "read_task")
        finally:
            print("wait_readable finish")

    @_public
    async def wait_writable(self, sock):
        print("wait_writable start")
        try:
            await self._afd_poll(sock, "write_task")
        finally:
            print("wait_writable finish")

    @_public
    def notify_closing(self, handle):
        handle = _get_base_socket(handle)
        waiters = self._afd_waiters.get(handle)
        if waiters is not None:
            if waiters.read_task is not None:
                _core.reschedule(
                    waiters.read_task, outcome.Error(_core.ClosedResourceError())
                )
                waiters.read_task = None
            if waiters.write_task is not None:
                _core.reschedule(
                    waiters.write_task, outcome.Error(_core.ClosedResourceError())
                )
                waiters.write_task = None
            self._refresh_afd(handle)

    ################################################################
    # Regular overlapped operations
    ################################################################

    @_public
    def register_with_iocp(self, handle):
        self._register_with_iocp(handle, CKeys.WAIT_OVERLAPPED)

    @_public
    async def wait_overlapped(self, handle, lpOverlapped):
        handle = _handle(handle)
        if isinstance(lpOverlapped, int):
            lpOverlapped = ffi.cast("LPOVERLAPPED", lpOverlapped)
        if lpOverlapped in self._overlapped_waiters:
            raise _core.BusyResourceError(
                "another task is already waiting on that lpOverlapped"
            )
        task = _core.current_task()
        self._overlapped_waiters[lpOverlapped] = task
        raise_cancel = None

        def abort(raise_cancel_):
            nonlocal raise_cancel
            raise_cancel = raise_cancel_
            try:
                _check(kernel32.CancelIoEx(handle, lpOverlapped))
            except OSError as exc:
                if exc.winerror == ErrorCodes.ERROR_NOT_FOUND:
                    # Too late to cancel. If this happens because the
                    # operation is already completed, we don't need to
                    # do anything; presumably the IOCP thread will be
                    # reporting back about that completion soon. But
                    # another possibility is that the operation was
                    # performed on a handle that wasn't registered
                    # with our IOCP (ie, the user forgot to call
                    # register_with_iocp), in which case we're just
                    # never going to see the completion. To avoid an
                    # uncancellable infinite sleep in the latter case,
                    # we'll PostQueuedCompletionStatus here, and if
                    # our post arrives before the original completion
                    # does, we'll assume the handle wasn't registered.
                    _check(
                        kernel32.PostQueuedCompletionStatus(
                            self._iocp, 0, CKeys.LATE_CANCEL, lpOverlapped
                        )
                    )
                    # Keep the lpOverlapped referenced so its address
                    # doesn't get reused until our posted completion
                    # status has been processed. Otherwise, we can
                    # get confused about which completion goes with
                    # which I/O.
                    self._posted_too_late_to_cancel.add(lpOverlapped)
                else:  # pragma: no cover
                    raise _core.TrioInternalError(
                        "CancelIoEx failed with unexpected error"
                    ) from exc
            return _core.Abort.FAILED

        await _core.wait_task_rescheduled(abort)
        if lpOverlapped.Internal != 0:
            # the lpOverlapped reports the error as an NT status code,
            # which we must convert back to a Win32 error code before
            # it will produce the right sorts of exceptions
            code = ntdll.RtlNtStatusToDosError(lpOverlapped.Internal)
            if code == ErrorCodes.ERROR_OPERATION_ABORTED:
                if raise_cancel is not None:
                    raise_cancel()
                else:
                    # We didn't request this cancellation, so assume
                    # it happened due to the underlying handle being
                    # closed before the operation could complete.
                    raise _core.ClosedResourceError(
                        "another task closed this resource"
                    )
            else:
                raise_winerror(code)

    async def _perform_overlapped(self, handle, submit_fn):
        # submit_fn(lpOverlapped) submits some I/O
        # it may raise an OSError with ERROR_IO_PENDING
        # the handle must already be registered using
        # register_with_iocp(handle)
        # This always does a schedule point, but it's possible that the
        # operation will not be cancellable, depending on how Windows is
        # feeling today. So we need to check for cancellation manually.
        await _core.checkpoint_if_cancelled()
        lpOverlapped = ffi.new("LPOVERLAPPED")
        print(f"submitting {reprO(lpOverlapped)}")
        try:
            submit_fn(lpOverlapped)
        except OSError as exc:
            if exc.winerror != ErrorCodes.ERROR_IO_PENDING:
                raise
        await self.wait_overlapped(handle, lpOverlapped)
        return lpOverlapped

    @_public
    async def write_overlapped(self, handle, data, file_offset=0):
        with ffi.from_buffer(data) as cbuf:

            def submit_write(lpOverlapped):
                # yes, these are the real documented names
                offset_fields = lpOverlapped.DUMMYUNIONNAME.DUMMYSTRUCTNAME
                offset_fields.Offset = file_offset & 0xffffffff
                offset_fields.OffsetHigh = file_offset >> 32
                _check(
                    kernel32.WriteFile(
                        _handle(handle),
                        ffi.cast("LPCVOID", cbuf),
                        len(cbuf),
                        ffi.NULL,
                        lpOverlapped,
                    )
                )

            lpOverlapped = await self._perform_overlapped(handle, submit_write)
            # this is "number of bytes transferred"
            return lpOverlapped.InternalHigh

    @_public
    async def readinto_overlapped(self, handle, buffer, file_offset=0):
        print("readinto_overlapped start")
        t = _core.current_task()
        print(f"{t._cancel_points}, {t._schedule_points}")
        try:
            with ffi.from_buffer(buffer, require_writable=True) as cbuf:

                def submit_read(lpOverlapped):
                    offset_fields = lpOverlapped.DUMMYUNIONNAME.DUMMYSTRUCTNAME
                    offset_fields.Offset = file_offset & 0xffffffff
                    offset_fields.OffsetHigh = file_offset >> 32
                    _check(
                        kernel32.ReadFile(
                            _handle(handle),
                            ffi.cast("LPVOID", cbuf),
                            len(cbuf),
                            ffi.NULL,
                            lpOverlapped,
                        )
                    )

                lpOverlapped = await self._perform_overlapped(handle, submit_read)
                return lpOverlapped.InternalHigh
        finally:
            import sys
            print("readinto_overlapped done", sys.exc_info())
            print(f"{t._cancel_points}, {t._schedule_points}")

    ################################################################
    # Raw IOCP operations
    ################################################################

    @_public
    def current_iocp(self):
        return int(ffi.cast("uintptr_t", self._iocp))

    @contextmanager
    @_public
    def monitor_completion_key(self):
        key = next(self._completion_key_counter)
        queue = _core.UnboundedQueue()
        self._completion_key_queues[key] = queue
        try:
            yield (key, queue)
        finally:
            del self._completion_key_queues[key]
