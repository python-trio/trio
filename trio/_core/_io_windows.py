import math
import itertools
from contextlib import contextmanager
import socket as stdlib_socket
from select import select
import threading
from collections import deque

import attr

from .. import _core
from . import _public, _hazmat
from ._wakeup_socketpair import WakeupSocketpair

from ._windows_cffi import (
    ffi, kernel32, INVALID_HANDLE_VALUE, raise_winerror, Error,
)

# XX update this to match the new reality:
#
# How things fit together:
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
#
# We also have a dedicated thread for calling select.select(). Why would we do
# this, when everyone knows that IOCP is wonderful and awesome and way better
# than Unix-style nonblocking I/O?
#
# Well:
#
# 1) UDP sockets are pretty much entirely broken on IOCP, because for some
# reason they decided that the completion notification should fire when the
# packet hit the network, *not* when it entered the send buffer. So if you do
# send/wait/send/wait/... then you will have only 1 packet in flight at a time
# and it will suck. Chrome ran into this and switched back to nonblocking I/O:
#   https://bugs.chromium.org/p/chromium/issues/detail?id=442392
#   https://groups.google.com/a/chromium.org/forum/#!topic/net-dev/VTPH1D8M6Ds
# It would be possible to instead try to (somehow) estimate a good amount of
# send buffering and then try to keep that many packets in flight by hand
# (i.e., the await sendto() for packet N would return when packet N-k was
# notified as complete, for some value of k).
#
# 2) Even for TCP, IOCP recv is kind of messed up. Apparently if you pass in a
# big buffer, then this triggers some kind of Nagle-ish heuristic where it
# decides you maybe don't want your data promptly, and it will sit on partial
# reads for a while waiting for more data to arrive? Of course no-one knows
# how it actually works; the Chrome folks just know that it screwed up all
# their latency targets and again they stopped using it:
#    https://bugs.chromium.org/p/chromium/issues/detail?id=30144#
#    https://bugs.chromium.org/p/chromium/issues/detail?id=86515#
#
# IOCP for send is fine, I guess? And for TransmitFile it's the only way to
# go. And if you want to juggle 10,000 UDP sockets then maybe you need IOCP?
# But it takes a tremendous amount of code to wrap the Windows socket
# functions with IOCP friendly versions, and the benefits are very minor.
#
# The one limitation that we do need to watch out for is that select.select()
# is limited to only 512 sockets. This is pretty easy to fix, though -- we
# just need to use our own wrapper for select (or maybe WSAPoll). Eventually
# there will be some scaling issue due to the O(n) cost of these things, but
# on my laptop, select.select() with 3*512 descriptors (and nothing ready)
# takes <200 microseconds, so I doubt this will be a huge issue. And,
# well... not many people use Windows to run big performance servers.
#
# (The fact that wait_socket_{read,writ}able currently go via call_soon is
# probably a much bigger scaling issue.)
#
# If we do switch to WSAPoll, we might consider using QueueUserAPC to take
# that thread, similar to what one would do for WaitForMultipleObjectsEx.

# Interesting note: on Windows you can *check* writability by attempting to
# do a 0-byte send -- this returns EWOULDBLOCK if the socket is not writable.
# Is this also true for IOCP sends? If so then it's possible to check
# writability via IOCP... (at least for SOCK_STREAM, where I *believe* but
# should check that IOCP notifications are based on the socket buffer).
# Unfortunately this doesn't seem to work for readability: sock.recv(0) return
# b"" even if there's nothing to read. Could double-check against the
# low-level API in case Python is doing something.

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

def _handle(obj):
    # For now, represent handles as either cffi HANDLEs or as ints.  If you
    # try to pass in a file descriptor instead, it's not going to work
    # out. (For that msvcrt.get_osfhandle does the trick, but I don't know if
    # we'll actually need that for anything...) For sockets this doesn't
    # matter, Python never allocates an fd. So let's wait until we actually
    # encounter the problem before worrying about it.
    if type(obj) is int:
        return ffi.cast("HANDLE", obj)
    else:
        return obj

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
        self._iocp = _check(kernel32.CreateIoCompletionPort(
            INVALID_HANDLE_VALUE, ffi.NULL, 0, 0))
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
        self._socket_waiters["read"][self._main_thread_waker.wakeup_sock] = None

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
                target=self._iocp_thread_fn, name="trio-IOCP")
            self._iocp_thread.start()

        # Step 1: select for sockets, with the given timeout.
        # If there are events queued from the IOCP thread, then the timeout is
        # implicitly reduced to 0 b/c the wakeup socket has pending data in
        # it.

        def socket_ready(what, sock, result=_core.Value(None)):
            task = self._socket_waiters[what].pop(sock)
            _core.reschedule(task, result)

        def socket_check(what, sock):
            try:
                select([sock], [sock], [sock])
            except OSError as exc:
                socket_ready(what, sock, result=_core.Error(exc))

        def do_select():
            r_waiting = self._socket_waiters["read"]
            w_waiting = self._socket_waiters["write"]
            r1, w, r2 = select(r_waiting, w_waiting, r_waiting, timeout)
            return set(r1 + r2), w

        # We select for exceptional conditions on the readable set because on
        # Windows, a failed non-blocking connect shows up as
        # "exceptional". Everyone else uses "readable" for this, so we
        # normalize it.
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
                socket_ready("read", sock)
        for sock in w:
            socket_ready("write", sock)

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
                    info = CompletionKeyEventInfo(
                        lpOverlapped=
                            int(ffi.cast("uintptr_t", entry.lpOverlapped)),
                        dwNumberOfBytesTransferred=
                            entry.dwNumberOfBytesTransferred)
                    queue.put_nowait(info)

    def _iocp_thread_fn(self):
        while True:
            max_events = 1
            batch = ffi.new("OVERLAPPED_ENTRY[]", max_events)
            received = ffi.new("PULONG")
            # https://msdn.microsoft.com/en-us/library/windows/desktop/aa364988(v=vs.85).aspx
            try:
                _check(kernel32.GetQueuedCompletionStatusEx(
                    self._iocp, batch, max_events, received, 0xffffffff, 0))
            except OSError as exc:
                if exc.winerror == Error.ERROR_ABANDONED_WAIT_0:
                    # The IOCP handle was closed; time to shut down.
                    return
                else:
                    self._iocp_queue.append(exc)
                    return
            self._iocp_queue.append((batch, received[0]))
            self._main_thread_waker.wakeup_thread_and_signal_safe()

    @_public
    @_hazmat
    def current_iocp(self):
        return int(ffi.cast("uintptr_t", self._iocp))

    @_public
    @_hazmat
    def register_with_iocp(self, handle):
        handle = _handle(obj)
        # https://msdn.microsoft.com/en-us/library/windows/desktop/aa363862(v=vs.85).aspx
        _check(kernel32.CreateIoCompletionPort(handle, self._iocp, 0, 0))

    @_public
    @_hazmat
    async def wait_overlapped(self, handle, lpOverlapped):
        handle = _handle(obj)
        if isinstance(lpOverlapped, int):
            lpOverlapped = ffi.cast("LPOVERLAPPED", lpOverlapped)
        if lpOverlapped in self._overlapped_waiters:
            raise RuntimeError(
                "another task is already waiting on that lpOverlapped")
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
        await _core.yield_indefinitely(abort)
        if lpOverlapped.Internal != 0:
            if lpOverlapped.Internal == Error.ERROR_OPERATION_ABORTED:
                assert raise_cancel is not None
                raise_cancel()
            else:
                raise_winerror(lpOverlapped.Internal)

    @_public
    @_hazmat
    @contextmanager
    def completion_key_monitor(self):
        key = next(self._completion_key_counter)
        queue = _core.UnboundedQueue()
        self._completion_key_queues[key] = queue
        try:
            yield (key, queue)
        finally:
            del self._completion_key_queues[key]

    async def _wait_socket(self, which, sock):
        # Using socket objects rather than raw handles gives better behavior
        # if someone closes the socket while another task is waiting on it. If
        # we just kept the handle, it might be reassigned, and we'd be waiting
        # on who-knows-what. The socket object won't be reassigned, and it
        # switches its fileno() to -1, so we can detect the offending socket
        # and wake the appropriate task. This is a pretty minor benefit (I
        # think it can only make a difference if someone is closing random
        # sockets in another thread? And on unix we don't handle this case at
        # all), but hey, why not.
        if type(sock) is not stdlib_socket.socket:
            raise TypeError("need a stdlib socket")
        if sock in self._socket_waiters[which]:
            raise RuntimeError(
                "another task is already waiting to {} this socket"
                .format(which))
        self._socket_waiters[which][sock] = _core.current_task()
        def abort(_):
            del self._socket_waiters[which][sock]
            return _core.Abort.SUCCEEDED
        await _core.yield_indefinitely(abort)

    @_public
    @_hazmat
    async def wait_socket_readable(self, sock):
        await self._wait_socket("read", sock)

    @_public
    @_hazmat
    async def wait_socket_writable(self, sock):
        await self._wait_socket("write", sock)

    # This has cffi-isms in it and is untested... but it demonstrates the
    # logic we'll want when we start actually using overlapped I/O.
    #
    # @_public
    # @_hazmat
    # async def perform_overlapped(self, handle, submit_fn):
    #     # submit_fn(lpOverlapped) submits some I/O
    #     # it may raise an OSError with ERROR_IO_PENDING
    #     await _core.yield_if_cancelled()
    #     self.register_with_iocp(handle)
    #     lpOverlapped = ffi.new("LPOVERLAPPED")
    #     try:
    #         submit_fn(lpOverlapped)
    #     except OSError as exc:
    #         if exc.winerror != Error.ERROR_IO_PENDING:
    #             await _core.yield_briefly_no_cancel()
    #             raise
    #     await self.wait_overlapped(handle, lpOverlapped)
    #     return lpOverlapped
