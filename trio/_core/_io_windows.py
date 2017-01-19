import math
from itertools import count

from .. import _core
from . import _public, _hazmat

# pywin32 appears to be pretty useless for our purposes -- missing lots of
# basic stuff like CancelIOEx, GetQueuedCompletionStatusEx, UDP support.

from ._windows_cffi import (
    ffi, kernel32, ws2_32, INVALID_HANDLE_VALUE,
    raise_GetLastError, raise_WSAGetLastError, Error,
)

__all__ = ["WindowsIOManager"]

def _check(success):
    if not success:
        raise_GetLastError()
    return success

# How things fit together:
# - each event (OVERLAPPED_ENTRY) contains:
#   - the "completion key"
#   - pointer to OVERLAPPED
#   - dwNumberOfBytesTransferred
# - also, for regular I/O, the OVERLAPPED structure gets updated with:
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

class WindowsIOManager:
    def __init__(self):
        # https://msdn.microsoft.com/en-us/library/windows/desktop/aa363862(v=vs.85).aspx
        self._iocp = _check(kernel32.CreateIoCompletionPort(
            INVALID_HANDLE_VALUE, ffi.NULL, 0, 0))
        if not self._iocp:  # pragma: no cover
            raise_GetLastError()
        self._registered = {}

        self._completion_key_counter = count(1)

        self._wakeup_flag = False
        self._wakeup_waiters = set()
        self._wakeup_completion_key = next(self._completion_key_counter)

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
            # just in case of confusion about where an event, this is more
            # unique than 0 and might help debugging.
            self._iocp, 12345, self._wakeup_completion_key, ffi.NULL))

    async def until_woken(self):
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
        # We want to pull out *all* the events, every time. Otherwise weird
        # thing could happen.
        #
        # +100 is a wild guess to cover for incoming wakeup_threadsafe
        # events. In general this could probably be optimized much more
        # (re-use the event buffer, coalesce wakeup_threadsafe events, etc.).
        max_events = len(self._registered) + 100
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
                else:
                    raise
            batches.append((batch, received))
            if received[0] == max_events:
                max_events *= 2
                timeout_ms = 0

        for batch, received in batches:
            for i in range(received[0]):
                entry = batch[i]
                if entry.lpCompletionKey == 0:
                    # Regular I/O event, dispatch on lpOverlapped
                    XX
                elif entry.lpCompletionKey == self._wakeup_completion_key:
                    if self._wakeup_waiters:
                        while self._wakeup_waiters:
                            _core.reschedule(self._wakeup_waiters.pop())
                    else:
                        self._wakeup_flag = True
                else:
                    # dispatch on lpCompletionKey
                    XX

    @_public
    @_hazmat
    def register_with_iocp(self, handle):
        # XX CreateIoCompletionPort
        pass

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



# We *always* need to check for cancellation before issuing an IOCP call
# so: let's have the lowest-level API be one where you do some standard prep
# -- associate object w/ IOCP and fetch OVERLAPPED? -- and that checks for
# cancellation.

# Some sort of convenience thing, like a context manager maybe?, to handle the
# idiomatic pattern of
#
# raise_if_cancelled()
# bind the handle to the IOCP if necessary
# DoWhateverEx()
# if it executed synchronously:
#     # maybe this is only *necessary* if it errored out?
#     await yield_briefly_no_cancel()
#     return result
# else:
#     info = await iocp_complete(handle, overlapped_object)
#     return result
#
# (since CancelIoEx is always the same, and takes handle + lpoverlapped)

# also maybe we should provide low-level wrappers like WSASend here, exposing
# the flags etc.?
