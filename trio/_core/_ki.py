import threading
from contextlib import contextmanager
from functools import wraps
import signal
import sys
import inspect

import attr

from . import _hazmat
from ._exceptions import KeyboardInterruptCancelled

__all__ = ["enable_ki_protection", "disable_ki_protection",
           "ki_protected"]

# In ordinary single-threaded Python code, when you hit control-C, it raises
# an exception and automatically does all the regular unwinding stuff.
#
# It trio code, we would like hitting control-C to raise an exception and
# automatically do all the regular unwinding stuff. In particular, we would
# like to maintain our invariant that all tasks always run to completion (one
# way or another), by unwinding all of them.
#
# But it's basically impossible to write the core task running code in such a
# way that it can maintain this invariant in the face of KeyboardInterrupt
# exceptions arising at arbitrary bytecode positions. Similarly, if a
# KeyboardInterrupt happened at the wrong moment inside pretty much any of our
# inter-task synchronization or I/O primitives, then the system state could
# get corrupted and prevent our being able to clean up properly.
#
# So, we need a way to defer KeyboardInterrupt processing from these critical
# sections.
#
# Things that don't work:
#
# - Listen for SIGINT and process it in a system task: works fine for
#   well-behaved programs that regularly pass through the event loop, but if
#   user-code goes into an infinite loop then it can't be interrupted. Which
#   is unfortunate, since dealing with infinite loops is what
#   KeyboardInterrupt is for!
#
# - Use pthread_sigmask to disable signal delivery during critical section:
#   (a) windows has no pthread_sigmask, (b) python threads start with all
#   signals unblocked, so if there are any threads around they'll receive the
#   signal and then tell the main thread to run the handler, even if the main
#   thread has that signal blocked.
#
# - Install a signal handler which checks a global variable to decide whether
#   to raise the exception immediately (if we're in a non-critical section),
#   or to schedule it on the event loop (if we're in a critical section). The
#   problem here is that it's impossible to transition safely out of user code:
#
#     with keyboard_interrupt_enabled:
#         msg = coro.send(value)
#
#   If this raises a KeyboardInterrupt, it might be because the coroutine got
#   interrupted and has unwound... or it might be the KeyboardInterrupt
#   arrived just *after* 'send' returned, so the coroutine is still running
#   but we just lost the message it sent. (And worse, in our actual task
#   runner, the send is hidden inside a utility function etc.)
#
# Solution:
#
# Mark *stack frames* as being interrupt-safe or interrupt-unsafe, and from
# the signal handler check which kind of frame we're currently in when
# deciding whether to raise or schedule the exception.
#
# There are still some cases where this can fail, like if someone hits
# control-C while the process is in the event loop, and then it immediately
# enters an infinite loop in user code. In this case the user has to hit
# control-C a second time. And of course if the user code is written so that
# it doesn't actually exit after a task crashes and everything gets cancelled,
# then there's not much to be done. (Hitting control-C repeatedly might help,
# but in general the solution is to kill the process some other way, just like
# for any Python program that's written to catch and ignore
# KeyboardInterrupt.)

# We use this class object as a unique key into the frame locals dictionary,
# which in particular is guaranteed not to clash with any possible real local
# name (I bet this will confuse some debugger at some point though...):
class LOCALS_KEY_KI_PROTECTION_ENABLED:
    pass

# NB: according to the signal.signal docs, 'frame' can be None on entry to
# this function:
def ki_protection_enabled(frame):
    while frame is not None:
        if LOCALS_KEY_KI_PROTECTION_ENABLED in frame.f_locals:
            return frame.f_locals[LOCALS_KEY_KI_PROTECTION_ENABLED]
        frame = frame.f_back
    return False

@_hazmat
def ki_protected():
    return ki_protection_enabled(sys._getframe())

def _ki_protection_decorator(enabled):
    def decorator(fn):
        if inspect.iscoroutinefunction(fn):
            @wraps(fn)
            async def wrapper(*args, **kwargs):
                locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = enabled
                return await fn(*args, **kwargs)
            return wrapper
        else:
            @wraps(fn)
            def wrapper(*args, **kwargs):
                locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = enabled
                return fn(*args, **kwargs)
            return wrapper
    return decorator

enable_ki_protection = _ki_protection_decorator(True)
enable_ki_protection.__name__ = "enable_ki_protection"
_hazmat(enable_ki_protection)

disable_ki_protection = _ki_protection_decorator(False)
disable_ki_protection.__name__ = "disable_ki_protection"
_hazmat(enable_ki_protection)

@contextmanager
def ki_manager(notify_cb):
    if (threading.current_thread() != threading.main_thread()
          or signal.getsignal(signal.SIGINT) != signal.default_int_handler):
        yield
        return

    def handler(signum, frame):
        assert signum == signal.SIGINT
        protection_enabled = ki_protection_enabled(frame)
        notify_cb(protection_enabled)
        if not protection_enabled:
            raise KeyboardInterruptCancelled

    signal.signal(signal.SIGINT, handler)
    try:
        yield
    finally:
        if signal.getsignal(signal.SIGINT) is handler:
            signal.signal(signal.SIGINT, signal.default_int_handler)
