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
    ffi, kernel32, ws2_32, INVALID_HANDLE_VALUE,
    raise_winerror, raise_WSAGetLastError, Error,
    SIO_GET_EXTENSION_FUNCTION_POINTER, WSAID_ACCEPTEX,
)

__all__ = ["AcceptEx", "ConnectEx", ]

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

def _check(success):
    if not success:
        raise_winerror()
    return success

def _WSAcheck(success):
    if not success:
        raise_WSAGetLastError()
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

@attr.s(frozen=True)
class CompletionKeyEventInfo:
    lpOverlapped = attr.ib()
    dwNumberOfBytesTransferred = attr.ib()

class _SelectThread:
    def __init__(self, call_soon):
        self.call_soon = call_soon
        self.waiters = {"read": {}, "write": {}}
        self.wakeup_main, self.wakeup_thread = socket.socketpair()
        self.wakeup_main.setblocking(False)
        self.wakeup_thread.setblocking(False)
        self.readable_waiters[self.wakeup_thread] = None
        self.thread_done = False
        self.thread = threading.Thread(target=self._thread)
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
    def _select_thread(self):
        while True:
            # We select for exceptional conditions on the readable set because
            # on Windows, non-blocking connect shows up as "exceptional"
            # rather than "readable" if the connect fails.
            #
            # select() holds the GIL while reading the input sets, so this is
            # safe.
            got = select(self.waiters["read"],
                         self.waiters["write"],
                         self.waiters["read"])
            readable1, writable, readable2 = got
            for sock in set(readable1 + readable2):
                if sock != self.wakeup_thread:
                    self.call_soon(self._wake, "read", sock)
            for sock in writable:
                self.call_soon(self._wake, "write", sock)
            # Drain
            while True:
                try:
                    self.wakeup_thread.recv(4096)
                except BlockingIOError:
                    pass
            if self.thread_done:
                return

    def _wake(self, which, sock):
        try:
            task = self.waiters[which].pop(sock)
        except KeyError as exc:
            # Must have gotten cancelled while the select was running
            assert exc.args == (sock,)
            return
        _core.reschedule(task)

    async def wait(self, which, sock):
        if sock in self.waiters[which]:
            raise RuntimeError(
                "another task is already waiting to {} this socket"
                .format(which))
        self.waiters[which][sock] = _core.current_task()
        def abort():
            del self.waiters[which][sock]
            return _core.Abort.SUCCEEDED
        await _core.yield_indefinitely(abort)

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
            tasks_waiting_socket_readable=len(self._sock_readable_waiters),
            tasks_waiting_socket_writable=len(self._sock_writable_waiters),
        )

    def close(self):
        if self._iocp is not None:
            _check(kernel32.CloseHandle(self._iocp))
            self._iocp = None

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
        queue = _core.Queue(_core.Queue.UNLIMITED)
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

################################################################
# Wrappers
################################################################

# XX maybe split the rest of this out into its own module? It doesn't actually
# use any non-public APIs...

# Fetch the magic winsocket pointers at startup
pointers = {}
_sock = stdlib_socket.socket()
for name, guid, ctype in [
        ("AcceptEx", WSAID_ACCEPTEX, "AcceptEx*"),
]:
    funcptr = ffi.new(ctype)
    lpcbBytesReturned = ffi.new("LPDWORD")
    # https://msdn.microsoft.com/en-us/library/ms741621%28VS.85%29.aspx
    failed = ws2_32.WSAIoctl(
        _sock.fileno(), SIO_GET_EXTENSION_FUNCTION_POINTER,
        WSAID_ACCEPTEX, ffi.sizeof("GUID"),
        funcptr, ffi.sizeof(funcptr),
        lpcbBytesReturned, ffi.NULL, ffi.NULL)
    if failed:
        raise_WSAGetLastError()
    assert lpcbBytesReturned[0] == ffi.sizeof(funcptr)
    pointers[name] = funcptr[0]
_sock.close()

# takes a pre-resolved Python-style AF_INET or AF_INET6 address
# returns sockaddr_in{,6}*
def _address_to_sockaddr(family, address):
    if family == stdlib_socket.AF_INET:
        assert len(address) == 2
        host, port = address
        sockaddr = ffi.new("struct sockaddr_in*")
        sockaddr.sin_family = family
        sockaddr.sin_port = port
        sockaddr.sin_addr = stdlib_socket.inet_pton(family, host)
        return sockaddr
    elif family == stdlib_socket.AF_INET6:
        assert len(address) >= 2
        while len(address) < 4:
            address += (0,)
        host, port, flowinfo, scopeid = address
        sockaddr = ffi.new("struct sockaddr_in6*")
        sockaddr.sin6_family = family
        sockaddr.sin6_port = port
        sockaddr.sin6_addr = stdlib_socket.inet_pton(family, host)
        sockaddr.sin6_flowinfo = flowinfo
        sockaddr.sin6_scope_id = scopeid
        return sockaddr
    else:
        raise ValueError("Only AF_INET and AF_INET6 are supported")

def _sockaddr_to_address(sockaddr, sockaddr_len):
    family = ffi.cast("struct sockaddr_in*", sockaddr).sin_family
    if family == stdlib_socket.AF_INET:
        assert sockaddr_len >= ffi.sizeof("struct sockaddr_in")
        sockaddr_in = ffi.cast("struct sockaddr_in*", sockaddr)
        host = stdlib_socket.socket.inet_ntop(
            family, bytes(sockaddr_in.sin_addr))
        post = sockaddr_in.sin_port
        return (host, port)
    elif sockaddr_in.sin_family == stdlib_socket.AF_INET6:
        assert sockaddr_len >= ffi.sizeof("struct sockaddr_in6")
        sockaddr_in6 = ffi.cast("struct sockaddr_in6*", sockaddr)
        host = stdlib_socket.socket.inet_ntop(
            family, bytes(sockaddr_in6.sin6_addr))
        port = sockaddr_in6.sin6_port
        flowinfo = sockaddr_in6.sin6_flowinfo
        scopeid = sockaddr_in6.sin6_scope_id
        return (host, port, flowinfo, scopeid)
    else:
        raise ValueError("Unrecognized address family {}".format(family))

@_hazmat
async def AcceptEx(
        sListenSocket, sAcceptSocket, lpOutputBuffer, dwReceiveDataLength,
        dwLocalAddressLength, dwRemoteAddressLength,
        ):
    # need to pin this so on PyPy we can be sure the gc won't move the
    # buffer while we're waiting for the overlapped I/O to complete.
    c_lpOutputBuffer = ffi.from_buffer(lpOutputBuffer)
    lpdwBytesReceived = ffi.new("LPDWORD")
    def submit_fn(lpOverlapped):
        # https://msdn.microsoft.com/en-us/library/ms737524(v=vs.85).aspx
        _WSAcheck(pointers["AcceptEx"](
            sListenSocket, sAcceptSocket, c_lpOutputBuffer,
            dwReceiveDataLength, dwLocalAddressLength,
            dwRemoteAddressLength, lpdwBytesReceived, lpOverlapped))
    await _core.perform_overlapped(sListenSocket, submit_fn)
    return lpdwBytesReceived[0]

@_hazmat
# s is a SOCKET integer
# family is AF_INET or AF_INET6
# address is a Python-style address e.g. ("127.0.0.1", 80). Must be
# pre-resolved.
# lpSendBuffer is a bytes-like of data to send when connecting.
#
async def ConnectEx(s, family, address, lpSendBuffer=b""):
    c_lpSendBuffer = ffi.from_buffer(lpSendBuffer)
    lpdwBytesSent = ffi.new("LPDWORD")
    sockaddr = _address_to_sockaddr(family, address)
    def submit_fn(lpOverlapped):
        # https://msdn.microsoft.com/en-us/library/ms737606(v=vs.85).aspx
        _WSAcheck(ws2_32.ConnectEx(
            s, sockaddr, ffi.sizeof(sockaddr[0]),
            lpSendBuffer, len(lpSendBuffer),
            lpdwBytesSent, lpOverlapped))
    await _core.perform_overlapped(s, submit_fn)
    return lpdwBytesSent[0]

@_hazmat
async def WSARecvFrom(s, bufs, lens, flags):
    # returns: (number of bytes received, flags, address)
    lpBuffers = ffi.new("WSABUF[]", len(bufs))
    for i in range(len(bufs)):
        lpBuffers[i].len = lens[i]
        lpBuffers[i].buf = ffi.from_buffer(bufs[i])
    lpNumberOfBytesRecvd = ffi.new("LPDWORD")
    lpFlags = ffi.new("LPDWORD")
    lpFlags[0] = flags
    lpFrom = ffi.new("struct sockaddr_in6*")
    lpFromlen = ffi.new("LPINT")
    lpFromlen[0] = ffi.sizeof(lpFrom[0])
    def submit_fn(lpOverlapped):
        # https://msdn.microsoft.com/en-us/library/ms741686(v=vs.85).aspx
        # "If no error occurs ... WSARecvFrom returns zero"
        # omgwtfbbqasdfjijfio
        _WSAcheck(not ws2_32.WSARecvFrom(
            s, lpBuffers, len(bufs),
            # "Use NULL for this parameter if the lpOverlapped parameter is
            # not NULL to avoid potentially erroneous results."
            ffi.NULL,
            lpFlags, lpFrom, lpFromlen, ffi.NULL))
    lpOverlapped = await _core.perform_overlapped(s, submit_fn)
    address = _sockaddr_to_address(lpFrom, lpFromlen[0])
    # InternalHigh is number-of-bytes-received
    return (lpOverlapped.InternalHigh, lpFlags[0], address)

# writeable on windows:
# http://stackoverflow.com/a/28848834
# maybe this is usable? (Windows 8+ only though :-()
# https://msdn.microsoft.com/en-us/library/windows/desktop/ms741576(v=vs.85).aspx
# -> can't figure out how to hook events up to iocp :-(
# also of note:
# - to be usable with IOCP, you have to pass a special flag when *creating*
# socket or file objects, and this can affect the semantics of other
# operations on them.
#   - Python's socket.socket() constructor *does* pass this flag
#   - there's ReOpenFile, but it may not work in all cases:
#     https://msdn.microsoft.com/en-us/library/aa365497%28VS.85%29.aspx
#     https://stackoverflow.com/questions/2475713/is-it-possible-to-change-handle-that-has-been-opened-for-synchronous-i-o-to-be-o
#     DuplicateHandle does *not* work for this
#       https://blogs.msdn.microsoft.com/oldnewthing/20140711-00/?p=523
#       https://msdn.microsoft.com/en-us/library/windows/desktop/ms741565(v=vs.85).aspx
#   - stdin/stdout are a bit of a problem in this regard (e.g. IPython) -
#     console handle does not have the special flag set :-(. There is simply
#     no way to do overlapped I/O on console handles, you have to use threads.
#   - it is at least possible to detect this, b/c when you try to associate
#     the handle with the IOCP then it will fail. can fall back on threads or
#     whatever at that point.
# - cancellation exists, but you still have to wait for the cancel to finish
# (and there's a race, so it might fail -- the operation might complete
# successfully even though you tried to cancel it)
# this means we can't depend on synchronously cancelling stuff.
# - if a file handle has the special overlapped flag set, then it doesn't have
# a file position, you can *only* do pread/pwrite
# -
# https://msdn.microsoft.com/en-us/library/windows/desktop/ms740087(v=vs.85).aspx
# says that after you cancel a socket operation, the only valid operation is
# to immediately close that socket. this isn't mentioned anywhere else though...
