import math
import itertools

import outcome
from contextlib import contextmanager
import socket as stdlib_socket
from select import select
import threading
from collections import deque
import signal

import attr

from .. import _core
from . import _public
from ._wakeup_socketpair import WakeupSocketpair
from .._util import is_main_thread

from ._windows_cffi import (
    ffi,
    kernel32,
    INVALID_HANDLE_VALUE,
    raise_winerror,
    ErrorCodes,
    _handle,
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
# Job notifications: effectively uses PostQueuedCompletionStatus, the
# "completion key" is used to identify which job we're talking about, and the
# other two scalars are overloaded to contain arbitrary data.
#
# So our strategy is:
# - when binding handles to the IOCP, we always set the completion key to 0.
#   when dispatching received events, when the completion key is 0 we dispatch
#   based on lpOverlapped
# - thread-safe wakeup uses completion key 1
# - other completion keys are available for user use

# handles:
# - for now we'll just use 1 thread per handle, should file a QoI bug to
#   multiplex multiple handles onto the same thread
# - cancel via QueueUserAPC
# - I'm a little nervous about the callback to QueueUserAPC... cffi's
#   ABI-level callbacks require executable memory and who knows how happy the
#   re-enter-Python code will be about being executed in APC context. (I guess
#   APC context here is always "on a thread running Python code but that has
#   dropped the GIL", so maybe there's no issue?)
#   - on 32-bit windows, Sleep makes a great QueueUserAPC callback...
#   - WakeByAddressAll and WakeByAddresSingle have the right signature
#     everywhere!
#     - there are also a bunch that take a *-sized arg and return BOOL,
#       e.g. CloseHandle, SetEvent, etc.
#   - or free() from the CRT (free(NULL) is a no-op says the spec)
#   - but do they have the right calling convention? QueueUserAPC wants an
#       APCProc which is VOID CALLBACK f(ULONG_PTR)
#       CALLBACK = __stdcall
#     ugh, and free is not annotated, so probably __cdecl
#     but most of the rest are WINAPI which is __stdcall
#     ...but, on x86-64 calling convention distinctions are erased! so we can
#     do Sleep on x86-32 and free on x86-64...


def _check(success):
    if not success:
        raise_winerror()
    return success


@attr.s(frozen=True)
class _WindowsStatistics:
    tasks_waiting_overlapped = attr.ib()
    completion_key_monitors = attr.ib()
    tasks_waiting_socket_readable = attr.ib()
    tasks_waiting_socket_writable = attr.ib()
    iocp_backlog = attr.ib()
    backend = attr.ib(default="windows")


@attr.s(frozen=True)
class CompletionKeyEventInfo:
    lpOverlapped = attr.ib()
    dwNumberOfBytesTransferred = attr.ib()


class WindowsIOManager:
    def __init__(self):
        # https://msdn.microsoft.com/en-us/library/windows/desktop/aa363862(v=vs.85).aspx
        self._closed = True
        self._iocp = _check(
            kernel32.CreateIoCompletionPort(
                INVALID_HANDLE_VALUE, ffi.NULL, 0, 0
            )
        )
        self._closed = False
        self._iocp_queue = deque()
        self._iocp_thread = None
        self._overlapped_waiters = {}
        self._completion_key_queues = {}
        # Completion key 0 is reserved for regular IO events
        self._completion_key_counter = itertools.count(1)

        # {stdlib socket object: task}
        # except that wakeup socket is mapped to None
        self._socket_waiters = {"read": {}, "write": {}}
        self._main_thread_waker = WakeupSocketpair()
        wakeup_sock = self._main_thread_waker.wakeup_sock
        self._socket_waiters["read"][wakeup_sock] = None

        # This is necessary to allow control-C to interrupt select().
        # https://github.com/python-trio/trio/issues/42
        if is_main_thread():
            fileno = self._main_thread_waker.write_sock.fileno()
            self._old_signal_wakeup_fd = signal.set_wakeup_fd(fileno)

    def statistics(self):
        return _WindowsStatistics(
            tasks_waiting_overlapped=len(self._overlapped_waiters),
            completion_key_monitors=len(self._completion_key_queues),
            tasks_waiting_socket_readable=len(self._socket_waiters["read"]),
            tasks_waiting_socket_writable=len(self._socket_waiters["write"]),
            iocp_backlog=len(self._iocp_queue),
        )

    def close(self):
        if not self._closed:
            self._closed = True
            _check(kernel32.CloseHandle(self._iocp))
            if self._iocp_thread is not None:
                self._iocp_thread.join()
            self._main_thread_waker.close()
            if is_main_thread():
                signal.set_wakeup_fd(self._old_signal_wakeup_fd)

    def __del__(self):
        # Need to make sure we clean up self._iocp (raw handle) and the IOCP
        # thread.
        self.close()

    def handle_io(self, timeout):
        # Step 0: the first time through, initialize the IOCP thread
        if self._iocp_thread is None:
            # The rare non-daemonic thread -- close() should always be called,
            # even on error paths, and we want to join it there.
            self._iocp_thread = threading.Thread(
                target=self._iocp_thread_fn, name="trio-IOCP"
            )
            self._iocp_thread.start()

        # Step 1: select for sockets, with the given timeout.
        # If there are events queued from the IOCP thread, then the timeout is
        # implicitly reduced to 0 b/c the wakeup socket has pending data in
        # it.
        def socket_ready(what, sock, result):
            task = self._socket_waiters[what].pop(sock)
            _core.reschedule(task, result)

        def socket_check(what, sock):
            try:
                select([sock], [sock], [sock], 0)
            except OSError as exc:
                socket_ready(what, sock, outcome.Error(exc))

        def do_select():
            r_waiting = self._socket_waiters["read"]
            w_waiting = self._socket_waiters["write"]
            # We select for exceptional conditions on the writable set because
            # on Windows, a failed non-blocking connect shows up as
            # "exceptional". Everyone else uses "writable" for this, so we
            # normalize it.
            r, w1, w2 = select(r_waiting, w_waiting, w_waiting, timeout)
            return r, set(w1 + w2)

        try:
            r, w = do_select()
        except OSError:
            # Some socket was closed or similar. Track it down and get rid of
            # it.
            for what in ["read", "write"]:
                for sock in self._socket_waiters[what]:
                    socket_check(what, sock)
            r, w = do_select()

        for sock in r:
            if sock is not self._main_thread_waker.wakeup_sock:
                socket_ready("read", sock, outcome.Value(None))
        for sock in w:
            socket_ready("write", sock, outcome.Value(None))

        # Step 2: drain the wakeup socket.
        # This must be done before checking the IOCP queue.
        self._main_thread_waker.drain()

        # Step 3: process the IOCP queue. If new events arrive while we're
        # processing the queue then we leave them for next time.
        # XX should probably have some sort emergency bail out if the queue
        # gets too long?
        for _ in range(len(self._iocp_queue)):
            msg = self._iocp_queue.popleft()
            if isinstance(msg, BaseException):
                # IOCP thread encountered some unexpected error -- give up and
                # let the user know.
                raise msg
            batch, received = msg
            for i in range(received):
                entry = batch[i]
                if entry.lpCompletionKey == 0:
                    # Regular I/O event, dispatch on lpOverlapped
                    waiter = self._overlapped_waiters.pop(entry.lpOverlapped)
                    _core.reschedule(waiter)
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

    def _iocp_thread_fn(self):
        # This thread sits calling GetQueuedCompletionStatusEx forever. To
        # signal that it should shut down, the main thread just closes the
        # IOCP, which causes GetQueuedCompletionStatusEx to return with an
        # error:
        IOCP_CLOSED_ERRORS = {
            # If the IOCP is closed while we're blocked in
            # GetQueuedCompletionStatusEx, then we get this error:
            ErrorCodes.ERROR_ABANDONED_WAIT_0,
            # If the IOCP is already closed when we initiate a
            # GetQueuedCompletionStatusEx, then we get this error:
            ErrorCodes.ERROR_INVALID_HANDLE,
        }
        while True:
            max_events = 1
            batch = ffi.new("OVERLAPPED_ENTRY[]", max_events)
            received = ffi.new("PULONG")
            # https://msdn.microsoft.com/en-us/library/windows/desktop/aa364988(v=vs.85).aspx
            try:
                _check(
                    kernel32.GetQueuedCompletionStatusEx(
                        self._iocp, batch, max_events, received, 0xffffffff, 0
                    )
                )
            except OSError as exc:
                if exc.winerror in IOCP_CLOSED_ERRORS:
                    # The IOCP handle was closed; time to shut down.
                    return
                else:
                    self._iocp_queue.append(exc)
                    return
            self._iocp_queue.append((batch, received[0]))
            self._main_thread_waker.wakeup_thread_and_signal_safe()

    @_public
    def current_iocp(self):
        return int(ffi.cast("uintptr_t", self._iocp))

    @_public
    def register_with_iocp(self, handle):
        handle = _handle(obj)
        # https://msdn.microsoft.com/en-us/library/windows/desktop/aa363862(v=vs.85).aspx
        _check(kernel32.CreateIoCompletionPort(handle, self._iocp, 0, 0))

    @_public
    async def wait_overlapped(self, handle, lpOverlapped):
        handle = _handle(obj)
        if isinstance(lpOverlapped, int):
            lpOverlapped = ffi.cast("LPOVERLAPPED", lpOverlapped)
        if lpOverlapped in self._overlapped_waiters:
            raise _core.ResourceBusyError(
                "another task is already waiting on that lpOverlapped"
            )
        task = _core.current_task()
        self._overlapped_waiters[lpOverlapped] = task
        raise_cancel = None

        def abort(raise_cancel_):
            # https://msdn.microsoft.com/en-us/library/windows/desktop/aa363792(v=vs.85).aspx
            # the _check here is probably wrong -- I guess we should just
            # ignore errors? but at least it will let us learn what errors are
            # possible -- the docs are pretty unclear.
            nonlocal raise_cancel
            raise_cancel = raise_cancel_
            _check(kernel32.CancelIoEx(handle, lpOverlapped))
            return _core.Abort.FAILED

        await _core.wait_task_rescheduled(abort)
        if lpOverlapped.Internal != 0:
            if lpOverlapped.Internal == ErrorCodes.ERROR_OPERATION_ABORTED:
                assert raise_cancel is not None
                raise_cancel()
            else:
                raise_winerror(lpOverlapped.Internal)

    @_public
    @contextmanager
    def monitor_completion_key(self):
        key = next(self._completion_key_counter)
        queue = _core.UnboundedQueue()
        self._completion_key_queues[key] = queue
        try:
            yield (key, queue)
        finally:
            del self._completion_key_queues[key]

    async def _wait_socket(self, which, sock):
        if not isinstance(sock, int):
            sock = sock.fileno()
        if sock in self._socket_waiters[which]:
            await _core.checkpoint()
            raise _core.ResourceBusyError(
                "another task is already waiting to {} this socket"
                .format(which)
            )
        self._socket_waiters[which][sock] = _core.current_task()

        def abort(_):
            del self._socket_waiters[which][sock]
            return _core.Abort.SUCCEEDED

        await _core.wait_task_rescheduled(abort)

    @_public
    async def wait_socket_readable(self, sock):
        await self._wait_socket("read", sock)

    @_public
    async def wait_socket_writable(self, sock):
        await self._wait_socket("write", sock)

    @_public
    def notify_socket_close(self, sock):
        if not isinstance(sock, int):
            sock = sock.fileno()
        for mode in ["read", "write"]:
            if sock in self._socket_waiters[mode]:
                task = self._socket_waiters[mode].pop(sock)
                exc = _core.ClosedResourceError(
                    "another task closed this socket"
                )
                _core.reschedule(task, outcome.Error(exc))

    # This has cffi-isms in it and is untested... but it demonstrates the
    # logic we'll want when we start actually using overlapped I/O.
    #
    # @_public
    # async def perform_overlapped(self, handle, submit_fn):
    #     # submit_fn(lpOverlapped) submits some I/O
    #     # it may raise an OSError with ERROR_IO_PENDING
    #     await _core.checkpoint_if_cancelled()
    #     self.register_with_iocp(handle)
    #     lpOverlapped = ffi.new("LPOVERLAPPED")
    #     try:
    #         submit_fn(lpOverlapped)
    #     except OSError as exc:
    #         if exc.winerror != Error.ERROR_IO_PENDING:
    #             await _core.cancel_shielded_checkpoint()
    #             raise
    #     await self.wait_overlapped(handle, lpOverlapped)
    #     return lpOverlapped
