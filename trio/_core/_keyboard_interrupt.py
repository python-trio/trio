import threading
from contextlib import contextmanager
import signal

import attr

# In ordinary single-threaded Python code, when you hit control-C, it raises
# an exception and automatically does all the regular unwinding stuff.
#
# We would like that in trio code, when you hit control-C, it raises an
# exception and automatically does all the regular unwinding stuff. In
# particular, we would like to maintain our invariant that all tasks always
# run to completion (one way or another).
#
# But it's basically impossible to write the core task running code in such a
# way that it can maintain this invariant in the face of KeyboardInterrupt
# exceptions arising at arbitrary bytecode positions.
#
# So, we need a way to defer KeyboardInterrupt processing from these critical
# sections.
#
# Things that don't work:
#
# - Listen for SIGINT and process it in a system task: works fine for
#   well-behaved programs that regularly pass through the event loop, but if
#   user-code goes into an infinite loop then it can't be interrupted. Which
#   is unfortunate, since this is what interrupts are for!
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
class LOCALS_KEY_KEYBOARD_INTERRUPT_SAFE:
    pass

# NB: according to the signal.signal docs, 'frame' can be None on entry to
# this function:
def _keyboard_interrupt_safe(frame):
    while frame is not None:
        if LOCALS_KEY_KEYBOARD_INTERRUPT_SAFE in frame.f_locals:
            return frame.f_locals[LOCALS_KEY_KEYBOARD_INTERRUPT_SAFE]
        frame = frame.f_back
    return False

@attr.s(slots=True)
class KeyboardInterruptStatus:
    pending = attr.ib(default=False)

@contextmanager
def keyboard_interrupt_manager(notify_cb):
    status = KeyboardInterruptStatus()
    if (threading.current_thread() != threading.main_thread()
          or signal.getsignal(signal.SIGINT) != signal.default_int_handler):
        yield status
        return

    def handler(signum, frame):
        assert signum == signal.SIGINT
        if _keyboard_interrupt_safe(frame):
            status.pending = False
            raise KeyboardInterrupt
        else:
            status.pending = True
            notify_cb(status)

    signal.signal(signal.SIGINT, handler)
    try:
        yield status
    finally:
        if signal.getsignal(signal.SIGINT) is handler:
            signal.signal(signal.SIGINT, signal.default_int_handler)
