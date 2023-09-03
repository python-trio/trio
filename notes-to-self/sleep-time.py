# Suppose:
# - we're blocked until a timeout occurs
# - our process gets put to sleep for a while (SIGSTOP or whatever)
# - then it gets woken up again
# what happens to our timeout?
#
# Here we do things that sleep for 6 seconds, and we put the process to sleep
# for 2 seconds in the middle of that.
#
# Results on Linux: everything takes 6 seconds, except for select.select(),
# and also time.sleep() (which on CPython uses the select() call internally)
#
# Results on macOS: everything takes 6 seconds.
#
# Why do we care:
# https://github.com/python-trio/trio/issues/591#issuecomment-498020805

import os
import select
import signal
import subprocess
import sys
import time

DUR = 6
# Can also try SIGTSTP
STOP_SIGNAL = signal.SIGSTOP

test_progs = [
    f"import threading; ev = threading.Event(); ev.wait({DUR})",
    # Python's time.sleep() calls select() internally
    f"import time; time.sleep({DUR})",
    # This is the real sleep() function
    f"import ctypes; ctypes.CDLL(None).sleep({DUR})",
    f"import select; select.select([], [], [], {DUR})",
    f"import select; p = select.poll(); p.poll({DUR} * 1000)",
]
if hasattr(select, "epoll"):
    test_progs += [
        f"import select; ep = select.epoll(); ep.poll({DUR})",
    ]
if hasattr(select, "kqueue"):
    test_progs += [
        f"import select; kq = select.kqueue(); kq.control([], 1, {DUR})",
    ]

for test_prog in test_progs:
    print("----------------------------------------------------------------")
    start = time.monotonic()
    print(f"Running: {test_prog}")
    print(f"Expected duration: {DUR} seconds")
    p = subprocess.Popen([sys.executable, "-c", test_prog])
    time.sleep(DUR / 3)
    print(f"Putting it to sleep for {DUR / 3} seconds")
    os.kill(p.pid, STOP_SIGNAL)
    time.sleep(DUR / 3)
    print("Waking it up again")
    os.kill(p.pid, signal.SIGCONT)
    p.wait()
    end = time.monotonic()
    print(f"Actual duration: {end - start:.2f}")
