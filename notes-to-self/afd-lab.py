# A little script to experiment with AFD polling.
#
# This cheats and uses a bunch of internal APIs. Don't follow its example. The
# point is just to experiment with random junk that probably won't work, so we
# can figure out what we actually do want to do internally.

# Currently this demonstrates what seems to be a weird bug in the Windows
# kernel. If you:
#
# 0. Set up a socket so that it's not writable.
# 1. Submit a SEND poll operation.
# 2. Submit a RECEIVE poll operation.
# 3. Send some data through the socket, to trigger the RECEIVE.
#
# ...then the SEND poll operation completes with the RECEIVE flag set.
#
# (This bug is why our Windows backend jumps through hoops to avoid ever
# issuing multiple polls simultaneously for the same socket.)
#
# This script's output on my machine:
#
# -- Iteration start --
# Starting a poll for <AFDPollFlags.AFD_POLL_SEND: 4>
# Starting a poll for <AFDPollFlags.AFD_POLL_RECEIVE: 1>
# Sending another byte
# Poll for <AFDPollFlags.AFD_POLL_SEND: 4>: got <AFDPollFlags.AFD_POLL_RECEIVE: 1>
# Poll for <AFDPollFlags.AFD_POLL_RECEIVE: 1>: Cancelled()
# -- Iteration start --
# Starting a poll for <AFDPollFlags.AFD_POLL_SEND: 4>
# Starting a poll for <AFDPollFlags.AFD_POLL_RECEIVE: 1>
# Poll for <AFDPollFlags.AFD_POLL_RECEIVE: 1>: got <AFDPollFlags.AFD_POLL_RECEIVE: 1> Sending another byte
# Poll for <AFDPollFlags.AFD_POLL_SEND: 4>: got <AFDPollFlags.AFD_POLL_RECEIVE: 1>
#
# So what we're seeing is:
#
# On the first iteration, where there's initially no data in the socket, the
# SEND completes with the RECEIVE flag set, and the RECEIVE operation doesn't
# return at all, until we cancel it.
#
# On the second iteration, there's already data sitting in the socket from the
# last loop. This time, the RECEIVE returns immediately with the RECEIVE flag
# set, which makes sense -- when starting a RECEIVE poll, it does an immediate
# check to see if there's data already, and if so it does an early exit. But
# the bizarre thing is, when we then send *another* byte of data, the SEND
# operation wakes up with the RECEIVE flag set.
#
# Why is this bizarre? Let me count the ways:
#
# - The SEND operation should never return RECEIVE.
#
# - If it does insist on returning RECEIVE, it should do it immediately, since
#   there is already data to receive. But it doesn't.
#
# - And then when we send data into a socket that already has data in it, that
#   shouldn't have any effect at all! But instead it wakes up the SEND.
#
# - Also, the RECEIVE call did an early check for data and exited out
#   immediately, without going through the whole "register a callback to
#   be notified when data arrives" dance. So even if you do have some bug
#   in tracking which operations should be woken on which state transitions,
#   there's no reason this operation would even touch that tracking data. Yet,
#   if we take out the brief RECEIVE, then the SEND *doesn't* wake up.
#
# - Also, if I move the send() call up above the loop, so that there's already
#   data in the socket when we start our first iteration, then you would think
#   that would just make the first iteration act like it was the second
#   iteration. But it doesn't. Instead it makes all the weird behavior
#   disappear entirely.
#
# "What do we know … of the world and the universe about us? Our means of
# receiving impressions are absurdly few, and our notions of surrounding
# objects infinitely narrow. We see things only as we are constructed to see
# them, and can gain no idea of their absolute nature. With five feeble senses
# we pretend to comprehend the boundlessly complex cosmos, yet other beings
# with wider, stronger, or different range of senses might not only see very
# differently the things we see, but might see and study whole worlds of
# matter, energy, and life which lie close at hand yet can never be detected
# with the senses we have."

import sys
import os.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + r"\.."))

import trio
print(trio.__file__)
import trio.testing
import socket

from trio._core._windows_cffi import (
    ffi, kernel32, AFDPollFlags, IoControlCodes, ErrorCodes
)
from trio._core._io_windows import (
    _get_base_socket, _afd_helper_handle, _check
)

class AFDLab:
    def __init__(self):
        self._afd = _afd_helper_handle()
        trio.lowlevel.register_with_iocp(self._afd)

    async def afd_poll(self, sock, flags, *, exclusive=0):
        print(f"Starting a poll for {flags!r}")
        lpOverlapped = ffi.new("LPOVERLAPPED")
        poll_info = ffi.new("AFD_POLL_INFO *")
        poll_info.Timeout = 2**63 - 1  # INT64_MAX
        poll_info.NumberOfHandles = 1
        poll_info.Exclusive = exclusive
        poll_info.Handles[0].Handle = _get_base_socket(sock)
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
            if exc.winerror != ErrorCodes.ERROR_IO_PENDING:  # pragma: no cover
                raise

        try:
            await trio.lowlevel.wait_overlapped(self._afd, lpOverlapped)
        except:
            print(f"Poll for {flags!r}: {sys.exc_info()[1]!r}")
            raise
        out_flags = AFDPollFlags(poll_info.Handles[0].Events)
        print(f"Poll for {flags!r}: got {out_flags!r}")
        return out_flags


def fill_socket(sock):
    try:
        while True:
            sock.send(b"x" * 65536)
    except BlockingIOError:
        pass


async def main():
    afdlab = AFDLab()

    a, b = socket.socketpair()
    a.setblocking(False)
    b.setblocking(False)

    fill_socket(a)

    while True:
        print("-- Iteration start --")
        async with trio.open_nursery() as nursery:
            nursery.start_soon(
                afdlab.afd_poll,
                a,
                AFDPollFlags.AFD_POLL_SEND,
            )
            await trio.sleep(2)
            nursery.start_soon(
                afdlab.afd_poll,
                a,
                AFDPollFlags.AFD_POLL_RECEIVE,
            )
            await trio.sleep(2)
            print("Sending another byte")
            b.send(b"x")
            await trio.sleep(2)
            nursery.cancel_scope.cancel()

trio.run(main)
