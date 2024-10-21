# This is a reproducer for:
#   https://bugs.python.org/issue30744
#   https://bitbucket.org/pypy/pypy/issues/2591/

import sys
import threading
import time

COUNT = 100


def slow_tracefunc(frame, event, arg):
    # A no-op trace function that sleeps briefly to make us more likely to hit
    # the race condition.
    time.sleep(0.01)
    return slow_tracefunc


def run_with_slow_tracefunc(fn):
    # settrace() only takes effect when you enter a new frame, so we need this
    # little dance:
    sys.settrace(slow_tracefunc)
    return fn()


def outer():
    x = 0
    # We hide the done variable inside a list, because we want to use it to
    # communicate between the main thread and the looper thread, and the bug
    # here is that variable assignments made in the main thread disappear
    # before the child thread can see them...
    done = [False]

    def traced_looper():
        # Force w_locals to be instantiated (only matters on PyPy; on CPython
        # you can comment this line out and everything stays the same)
        print(locals())
        nonlocal x  # Force x to be closed over
        # Random nonsense whose only purpose is to trigger lots of calls to
        # the trace func
        count = 0
        while not done[0]:
            count += 1
        return count

    t = threading.Thread(target=run_with_slow_tracefunc, args=(traced_looper,))
    t.start()

    for i in range(COUNT):
        print(f"after {i} increments, x is {x}")
        x += 1
        time.sleep(0.01)

    done[0] = True
    t.join()

    print(f"Final discrepancy: {COUNT - x} (should be 0)")


outer()
