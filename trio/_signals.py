import signal
import threading
from contextlib import contextmanager

from . import _core

__all__ = ["catch_signals"]

# Discussion of signal handling strategies:
#
# - On Windows signals barely exist. There are no options; signal handlers are
#   the only available API.
#
# - On Linux signalfd is arguably the natural way. Semantics: signalfd acts as
#   an *alternative* signal delivery mechanism. The way you use it is to mask
#   out the relevant signals process-wide (so that they don't get delivered
#   the normal way), and then when you read from signalfd that actually counts
#   as delivering it (despite the mask). The problem with this is that we
#   don't have any reliable way to mask out signals process-wide -- the only
#   way to do that in Python is to call pthread_sigmask from the main thread
#   *before starting any other threads*, and as a library we can't really
#   impose that, and the failure mode is annoying (signals get delivered via
#   signal handlers whether we want them to or not).
#
# - on MacOS/*BSD, kqueue is the natural way. Semantics: kqueue acts as an
#   *extra* signal delivery mechanism. Signals are delivered the normal
#   way, *and* are delivered to kqueue. So you want to set them to SIG_IGN so
#   that they don't end up pending forever (I guess?). I can't find any actual
#   docs on how masking and EVFILT_SIGNAL interact. I did see someone note
#   that if a signal is pending when the kqueue filter is added then you
#   *don't* get notified of that, which makes sense. But still, we have to
#   manipulate signal state (e.g. setting SIG_IGN) which as far as Python is
#   concerned means we have to do this from the main thread.
#
# So in summary, there don't seem to be any compelling advantages to using the
# platform-native signal notification systems; they're kinda nice, but it's
# simpler to implement the naive signal-handler-based system once and be
# done. (The big advantage would be if there were a reliable way to monitor
# for SIGCHLD from outside the main thread and without interfering with other
# libraries that also want to monitor for SIGCHLD. But there isn't. I guess
# kqueue might give us that, but in kqueue we don't need it, because kqueue
# can directly monitor for child process state changes.)

@contextmanager
def _signal_handler(signals, handler):
    original_handlers = {}
    for signum in signals:
        original_handlers[signum] = signal.signal(signum, handler)
    try:
        yield
    finally:
        for signum, original_handler in original_handlers.items():
            signal.signal(signum, original_handler)

# XX it would be nice if we could coalesce signals here so if a bunch arrive
# in a short time we don't require unbounded memory. This would need two things:
# - a coalesce=True argument to call_soon that tells it that the function is
#   hashable and idempotent. This would be implemented by having both a set
#   and a deque of pending call_soon thunks, and I guess we'd read the set in
#   a batched+threadsafe+signalsafe way by doing:
#     batch = thunk_set.copy()
#     for thunk in batch:
#         thunk_set.remove(thunk)
#         thunk.call()
#   (this assumes set.copy and set.remove are atomic operations, which I'm
#   pretty sure is correct).
# - We'd need a custom queue-like object for delivering signals, that does
#   coalescing.
@contextmanager
def catch_signals(signals):
    if threading.current_thread() != threading.main_thread():
        raise RuntimeError(
            "Sorry, catch_signals is only possible when running in the "
            "Python interpreter's main thread")
    call_soon = _core.current_call_soon_thread_and_signal_safe()
    queue = _core.UnboundedQueue()
    def handler(signum, _):
        call_soon(queue.put_nowait, signum)
    with _signal_handler(signals, handler):
        yield queue
