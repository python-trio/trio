import math
from itertools import count
from contextlib import contextmanager
import socket as stdlib_socket
from select import select
import threading

import attr

from .. import _core
from . import _public, _hazmat

# pywin32 appears to be pretty useless for our purposes -- missing lots of
# basic stuff like CancelIOEx, GetQueuedCompletionStatusEx, UDP support.

from ._windows_cffi import (
    ffi, kernel32, INVALID_HANDLE_VALUE, raise_winerror, Error,
)

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
    backend = attr.ib(default="windows")

class _SelectThread:
    def __init__(self, call_soon):
        self.call_soon = call_soon
        self.waiters = {"read": {}, "write": {}}
        self.wakeup_main, self.wakeup_thread = stdlib_socket.socketpair()
        self.wakeup_main.setblocking(False)
        self.wakeup_thread.setblocking(False)
        self.waiters["read"][self.wakeup_thread] = None
        self.thread_done = False
        self.thread = threading.Thread(target=self._thread_loop, daemon=True)
        self.thread.start()

    def statistics(self):
        return dict(
            tasks_waiting_socket_readable=len(self.waiters["read"]) - 1,
            tasks_waiting_socket_writable=len(self.waiters["write"]),
        )

    def _wakeup(self):
        try:
            self.wakeup_main.send(b"\x00")
        except BlockingIOError:
            pass

    def close(self):
        if self.thread is not None:
            self.thread_done = True
            self._wakeup()
            self.thread.join()
            self.thread = None
        self.wakeup_main.close()
        self.wakeup_thread.close()

    # XX could/should switch to calling select() directly, or WSAPoll, to
    # remove the 512 socket limit. (select() is actually about as efficient as
    # WSAPoll if you know how the fdset is structured.)
    def _thread_loop(self):
        while True:
            #print("looping")
            if self.thread_done:
                return
            #print("not done")
            # select() holds the GIL while reading the input sets, so this is
            # safe.
            wait_read = self.waiters["read"]
            wait_write = self.waiters["write"]
            #print("waiting", wait_read, wait_write)
            # We select for exceptional conditions on the readable set because
            # on Windows, non-blocking connect shows up as "exceptional"
            # rather than "readable" if the connect fails.
            got = select(wait_read, wait_write, wait_read)
            #print("woke up!", got)
            readable1, writable, readable2 = got
            for sock in set(readable1 + readable2):
                if sock != self.wakeup_thread:
                    self._wake("read", sock)
            for sock in writable:
                self._wake("write", sock)
            # Drain
            #print("draining")
            while True:
                try:
                    self.wakeup_thread.recv(4096)
                except BlockingIOError:
                    break

    def _wake(self, which, sock):
        try:
            task = self.waiters[which].pop(sock)
        except KeyError as exc:
            # Must have gotten cancelled while the select was running
            assert exc.args == (sock,)
            return
        self.call_soon(_core.reschedule, task)

    async def wait(self, which, sock):
        if type(sock) is not stdlib_socket.socket:
            raise TypeError("need a stdlib socket")
        if sock in self.waiters[which]:
            raise RuntimeError(
                "another task is already waiting to {} this socket"
                .format(which))
        self.waiters[which][sock] = _core.current_task()
        self._wakeup()
        def abort():
            del self.waiters[which][sock]
            return _core.Abort.SUCCEEDED
        await _core.yield_indefinitely(abort)


@attr.s(frozen=True)
class CompletionKeyEventInfo:
    lpOverlapped = attr.ib()
    dwNumberOfBytesTransferred = attr.ib()


class WindowsIOManager:
    def __init__(self):
        # https://msdn.microsoft.com/en-us/library/windows/desktop/aa363862(v=vs.85).aspx
        self._iocp = _check(kernel32.CreateIoCompletionPort(
            INVALID_HANDLE_VALUE, ffi.NULL, 0, 0))
        self._overlapped_waiters = {}
        self._completion_key_queues = {}

        self._completion_key_counter = count(1)

        # Defer creating it until the first call to handle_io, at which point
        # the call_soon_thread_and_signal_safe machinery is available.
        self._select_thread = None

        self._wakeup_flag = False
        self._wakeup_waiters = set()
        self._wakeup_completion_key = next(self._completion_key_counter)

    def statistics(self):
        return _WindowsStatistics(
            tasks_waiting_overlapped=len(self._overlapped_waiters),
            completion_key_monitors=len(self._completion_key_queues),
            **self._select_thread.statistics(),
        )

    def close(self):
        if self._iocp is not None:
            _check(kernel32.CloseHandle(self._iocp))
            self._iocp = None
        if self._select_thread is not None:
            self._select_thread.close()
            self._select_thread = None

    def __del__(self):
        self.close()

    def wakeup_threadsafe(self):
        # XX it might be nicer to skip calling this if the flag is already
        # set, to reduce redundant events in the kernel...
        # https://msdn.microsoft.com/en-us/library/windows/desktop/aa365458(v=vs.85).aspx
        _check(kernel32.PostQueuedCompletionStatus(
            # dwNumberOfBytesTransferred is ignored; we set it to 12345
            # to make it more obvious where this event comes from in case we
            # ever have some confusing debugging to do.
            self._iocp, 12345, self._wakeup_completion_key, ffi.NULL))

    async def wait_woken(self):
        if self._wakeup_flag:
            self._wakeup_flag = False
            return
        task = _core.current_task()
        def abort():
            self._wakeup_waiters.remove(task)
            return _core.Abort.SUCCEEDED
        self._wakeup_waiters.add(task)
        await _core.yield_indefinitely(abort)

    def handle_io(self, timeout):
        if self._select_thread is None:
            call_soon = _core.current_call_soon_thread_and_signal_safe()
            self._select_thread = _SelectThread(call_soon)
        # We want to pull out *all* the events, every time. Otherwise weird
        # thing could happen.
        #
        # +100 is a wild guess to cover for incoming wakeup_threadsafe
        # events. In general this function could probably be optimized much
        # more (re-use the event buffer, coalesce wakeup_threadsafe events,
        # etc.).
        max_events = len(self._overlapped_waiters) + 100
        batches = []
        timeout_ms = math.ceil(timeout * 1000)
        while True:
            batch = ffi.new("OVERLAPPED_ENTRY[]", max_events)
            received = ffi.new("PULONG")
            try:
                # https://msdn.microsoft.com/en-us/library/windows/desktop/aa364988(v=vs.85).aspx
                _check(kernel32.GetQueuedCompletionStatusEx(
                    self._iocp, batch, max_events, received, timeout_ms, 0))
            except OSError as exc:
                if exc.winerror == Error.STATUS_TIMEOUT:
                    break
                else:  # pragma: no cover
                    raise
            batches.append((batch, received))
            if received[0] == max_events:
                max_events *= 2
                timeout_ms = 0
            else:
                break

        for batch, received in batches:
            for i in range(received[0]):
                entry = batch[i]
                if entry.lpCompletionKey == 0:
                    # Regular I/O event, dispatch on lpOverlapped
                    waiter = self._overlapped_waiters.pop(entry.lpOverlapped)
                    _core.reschedule(waiter)
                elif entry.lpCompletionKey == self._wakeup_completion_key:
                    if self._wakeup_waiters:
                        while self._wakeup_waiters:
                            _core.reschedule(self._wakeup_waiters.pop())
                    else:
                        self._wakeup_flag = True
                else:
                    # dispatch on lpCompletionKey
                    queue = self._completion_key_queues[entry.lpCompletionKey]
                    info = CompletionKeyEventInfo(
                        lpOverlapped=
                            int(ffi.cast("uintptr_t", entry.lpOverlapped)),
                        dwNumberOfBytesTransferred=
                            entry.dwNumberOfBytesTransferred)
                    queue.put_nowait(info)

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
        assert lpOverlapped not in self._overlapped_waiters
        task = _core.current_task()
        self._overlapped_waiters[lpOverlapped] = task
        def abort():
            # https://msdn.microsoft.com/en-us/library/windows/desktop/aa363792(v=vs.85).aspx
            # the _check here is probably wrong -- I guess we should just
            # ignore errors? but at least it will let us learn what errors are
            # possible -- the docs are pretty unclear.
            _check(kernel32.CancelIoEx(handle, lpOverlapped))
            return _core.Abort.FAILED
        await _core.yield_indefinitely(abort)
        if lpOverlapped.Internal != 0:
            if lpOverlapped.Internal == Error.ERROR_OPERATION_ABORTED:
                await yield_if_cancelled()
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

    @_public
    @_hazmat
    async def wait_socket_readable(self, sock):
        await self._select_thread.wait("read", sock)

    @_public
    @_hazmat
    async def wait_socket_writable(self, sock):
        await self._select_thread.wait("write", sock)

    @_public
    @_hazmat
    async def perform_overlapped(self, handle, submit_fn):
        # submit_fn(lpOverlapped) submits some I/O
        # it may raise an OSError with ERROR_IO_PENDING
        await _core.yield_if_cancelled()
        self.register_with_iocp(handle)
        lpOverlapped = ffi.new("LPOVERLAPPED")
        try:
            submit_fn(lpOverlapped)
        except OSError as exc:
            if exc.winerror != Error.ERROR_IO_PENDING:
                await _core.yield_briefly_no_cancel()
                raise
        await self.wait_overlapped(handle, lpOverlapped)
        return lpOverlapped
