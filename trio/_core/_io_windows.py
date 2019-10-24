# you can't have multiple AFD_POLL's outstanding simultaneously on the same
# socket. They get mixed up and weird stuff happens -- like you get
# notifications for the first call's flag, but with the second call's
# lpOverlapped.
#
# so we need a muxing system like _io_epoll has
# I think we can set Exclusive=1 to cause the old one to disappear, maybe?
# though really... who knows what that even does. maybe CancelIoEx is safer.
#
# for this case, we can ignore CancelIoEx errors, or the possibility of
# forgetting register_with_iocp
# can even use a dedicated completion key
#
# track {handle: Waiters object (reader task, writer task, lpOverlapped)}
# track {lpOverlapped: Waiters object}
# when need to update wait, CancelIoEx(afd_handle, lpOverlapped)
#   and drop from the second dict
# then submit new lpOverlapped and store it in both places
# when event comes in, look it up in lpOverlapped table and figure out who to
# wake up
# when notify_closing, wake up both tasks and then refresh the wait
#
# consider making notify_closing work for more operations

import itertools
from contextlib import contextmanager
import errno

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
# To avoid this, we have to coalesce all operations on a single socket, which
# is slightly fiddly, though not really any worse than what we have to do for
# epoll.

@attr.s(slots=True, eq=False):
class AFDWaiters:
    read_task = attr.ib(default=None)
    write_task = attr.ib(default=None)
    current_lpOverlapped = attr.ib(default=None)


@attr.s(slots=True, eq=False, frozen=True)
class _WindowsStatistics:
    tasks_waiting_overlapped = attr.ib()
    completion_key_monitors = attr.ib()
    tasks_waiting_socket_readable = attr.ib()
    tasks_waiting_socket_writable = attr.ib()
    backend = attr.ib(default="windows")


# Maximum number of events to dequeue from the completion port on each pass
# through the run loop. Somewhat arbitrary. Should be large enough to collect
# a good set of tasks on each loop, but not so large to waste tons of memory.
# (Each call to trio.run allocates a buffer that's ~32x this number.)
MAX_EVENTS = 1000


@attr.s(frozen=True)
class CompletionKeyEventInfo:
    lpOverlapped = attr.ib()
    dwNumberOfBytesTransferred = attr.ib()


class WindowsIOManager:
    def __init__(self):
        # If this method raises an exception, then __del__ could run on a
        # half-initialized object. So initialize everything that __del__
        # touches to known values up front, before we do anything that can
        # fail.
        self._iocp = None
        self._afd = None

        self._iocp = _check(
            kernel32.CreateIoCompletionPort(
                INVALID_HANDLE_VALUE, ffi.NULL, 0, 0
            )
        )
        self._afd = _afd_helper_handle()
        self.register_with_iocp(self._afd)
        self._events = ffi.new("OVERLAPPED_ENTRY[]", MAX_EVENTS)

        # {lpOverlapped: task}
        # These tasks also carry (handle, lpOverlapped) in their
        # custom_sleep_data, unless they've already been cancelled or
        # rescheduled.
        self._overlapped_waiters = {}
        # These are all listed in overlapped_waiters too; these extra dicts
        # are to (a) catch when two tasks try to wait on the same socket at
        # the same time, (b) find tasks to wake up in notify_closing.
        # {SOCKET: task}
        self._wait_readable_tasks = {}
        self._wait_writable_tasks = {}
        self._posted_too_late_to_cancel = set()
        self._completion_key_queues = {}
        # Completion key 0 is reserved for regular IO events.
        # Completion key 1 is used by the fallback post from a regular
        # IO event's abort_fn to catch the user forgetting to call
        # register_with_iocp.
        self._completion_key_counter = itertools.count(2)

    def statistics(self):
        return _WindowsStatistics(
            tasks_waiting_overlapped=len(self._overlapped_waiters),
            completion_key_monitors=len(self._completion_key_queues),
            tasks_waiting_socket_readable=len(self._wait_readable_tasks),
            tasks_waiting_socket_writable=len(self._wait_writable_tasks),
        )

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

    def handle_io(self, timeout):
        # arbitrary limit
        received = ffi.new("PULONG")
        milliseconds = round(1000 * timeout)
        if timeout > 0 and milliseconds == 0:
            milliseconds = 1
        try:
            _check(kernel32.GetQueuedCompletionStatusEx(
                self._iocp, self._events, MAX_EVENTS, received, milliseconds, 0
            )
                   )
        except OSError as exc:
            if exc.winerror == ErrorCodes.WAIT_TIMEOUT:
                return
            raise
        for i in range(received[0]):
            entry = self._events[i]
            if entry.lpCompletionKey == 0:
                # Regular I/O event, dispatch on lpOverlapped
                print(f"waking {reprO(entry.lpOverlapped)}")
                waiter = self._overlapped_waiters.pop(entry.lpOverlapped)
                _core.reschedule(waiter)
            elif entry.lpCompletionKey == 1:
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

    @_public
    def current_iocp(self):
        return int(ffi.cast("uintptr_t", self._iocp))

    @_public
    def register_with_iocp(self, handle):
        handle = _handle(handle)
        # https://msdn.microsoft.com/en-us/library/windows/desktop/aa363862(v=vs.85).aspx
        # INVALID_PARAMETER seems to be used for both "can't register
        # because not opened in OVERLAPPED mode" and "already registered"
        _check(kernel32.CreateIoCompletionPort(handle, self._iocp, 0, 0))
        # Supposedly this makes things slightly faster, by disabling the
        # ability to do WaitForSingleObject(handle). We would never want to do
        # that anyway, so might as well get the extra speed (if any).
        # Ref: http://www.lenholgate.com/blog/2009/09/interesting-blog-posts-on-high-performance-servers.html
        _check(
            kernel32.SetFileCompletionNotificationModes(
                handle, CompletionModes.FILE_SKIP_SET_EVENT_ON_HANDLE
            )
        )

    def _try_cancel_io_ex_for_task(self, task):
        if task.custom_sleep_data is None:
            return
        handle, lpOverlapped = task.custom_sleep_data
        task.custom_sleep_data = None
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
                        self._iocp, 0, 1, lpOverlapped
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

    @_public
    def notify_closing(self, handle):
        handle = _get_base_socket(handle)
        for tasks in [self._wait_readable_tasks, self._wait_writable_tasks]:
            task = tasks.get(handle)
            if task is not None:
                self._try_cancel_io_ex_for_task(task)

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
        task.custom_sleep_data = (handle, lpOverlapped)
        raise_cancel = None

        def abort(raise_cancel_):
            nonlocal raise_cancel
            raise_cancel = raise_cancel_
            self._try_cancel_io_ex_for_task(task)
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

    async def _perform_overlapped(self, handle, submit_fn):
        # submit_fn(lpOverlapped) submits some I/O
        # it may raise an OSError with ERROR_IO_PENDING
        # the handle must already be registered using
        # register_with_iocp(handle)
        lpOverlapped = ffi.new("LPOVERLAPPED")
        print(f"submitting {reprO(lpOverlapped)}")
        try:
            submit_fn(lpOverlapped)
        except OSError as exc:
            if exc.winerror != ErrorCodes.ERROR_IO_PENDING:
                raise
        await self.wait_overlapped(handle, lpOverlapped)
        return lpOverlapped

    async def _afd_poll(self, sock, events, tasks):
        base_handle = _get_base_socket(sock)
        if base_handle in tasks:
            raise _core.BusyResourceError
        tasks[base_handle] = _core.current_task()

        poll_info = ffi.new("AFD_POLL_INFO *")
        poll_info.Timeout = 2**63 - 1  # INT64_MAX
        poll_info.NumberOfHandles = 1
        poll_info.Exclusive = 0
        poll_info.Handles[0].Handle = base_handle
        poll_info.Handles[0].Status = 0
        poll_info.Handles[0].Events = events

        def submit_afd_poll(lpOverlapped):
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

        try:
            await self._perform_overlapped(self._afd, submit_afd_poll)
        finally:
            del tasks[base_handle]

        print("status", poll_info.Handles[0].Status)
        print(repr(AFDPollFlags(poll_info.Handles[0].Events)))

    @_public
    async def wait_readable(self, sock):
        print("wait_readable start")
        await self._afd_poll(sock, READABLE_FLAGS, self._wait_readable_tasks)
        print("wait_readable finish")

    @_public
    async def wait_writable(self, sock):
        print("wait_writable start")
        await self._afd_poll(sock, WRITABLE_FLAGS, self._wait_writable_tasks)
        print("wait_writable finish")

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
