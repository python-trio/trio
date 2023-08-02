# This script completes correctly on macOS and FreeBSD 13.0-CURRENT, but hangs
# on FreeBSD 12.1. I'm told the fix will be backported to 12.2 (which is due
# out in October 2020).
#
# Upstream bug: https://bugs.freebsd.org/bugzilla/show_bug.cgi?id=246350

import select
import os
import threading

r, w = os.pipe()

os.set_blocking(w, False)

print("filling pipe buffer")
while True:
    try:
        os.write(w, b"x")
    except BlockingIOError:
        break

_, wfds, _ = select.select([], [w], [], 0)
print("select() says the write pipe is", "writable" if w in wfds else "NOT writable")

kq = select.kqueue()
event = select.kevent(w, select.KQ_FILTER_WRITE, select.KQ_EV_ADD)
kq.control([event], 0)

print("closing read end of pipe")
os.close(r)

_, wfds, _ = select.select([], [w], [], 0)
print("select() says the write pipe is", "writable" if w in wfds else "NOT writable")

print("waiting for kqueue to report the write end is writable")
got = kq.control([], 1)
print("done!")
print(got)
