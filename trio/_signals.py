import signal
import threading
from contextlib import contextmanager

from . import _core
from ._util import aiter_compat
from ._sync import Semaphore

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

# XX maybe it would make sense to merge this implementation with
# UnboundedQueue, via a tiny bit of code to let it use a set instead of a list
# for the intermediate storage? It's *almost* enough to just change
# UnboundedQueue.__init__ to do self._data = set() instead of self.data =
# list(), except for the list.append vs. set.add incompatibility...
class SignalQueue:
    def __init__(self):
        self._semaphore = Semaphore(0, max_value=1)
        self._pending = set()

    def _add(self, signum):
        if not self._pending:
            self._semaphore.release()
        self._pending.add(signum)

    @aiter_compat
    def __aiter__(self):
        return self

    async def __anext__(self):
        await self._semaphore.acquire()
        assert self._pending
        pending = set(self._pending)
        self._pending.clear()
        return pending

@contextmanager
def catch_signals(signals):
    """A context manager for catching signals.

    Entering this context manager starts listening for the given signals and
    returns an async iterator; exiting the context manager stops listening.

    Iterating the async iterator blocks until at least one signal has arrived,
    and then returns a :class:`set` containing all of the signals that were
    received since the last iteration. (This is generally similar to how
    :class:`UnboundedQueue` works, but since Unix semantics are that identical
    signals can/should be coalesced, here we use a :class:`set` for storage
    instead of a :class:`list`.)

    Args:
      signals: a set of signals to listen for.

    Raises:
      RuntimeError: if you try to use this anywhere except Python's main
          thread. (This is a Python limitation.)

    Example:

      A common convention for Unix daemon is that they should reload their
      configuration when they receive a ``SIGHUP``. Here's a sketch of what
      that might look like using :func:`catch_signals`::

         with trio.catch_signals({signal.SIGHUP}) as batched_signal_aiter:
             async for batch in batched_signal_aiter:
                 # We're only listening for one signal, so the batch is always
                 # {signal.SIGHUP}, but if we were listening to more signals
                 # then it could vary.
                 for signum in batch:
                     assert signum == signal.SIGHUP
                     reload_configuration()

    """
    if threading.current_thread() != threading.main_thread():
        raise RuntimeError(
            "Sorry, catch_signals is only possible when running in the "
            "Python interpreter's main thread")
    call_soon = _core.current_call_soon_thread_and_signal_safe()
    queue = SignalQueue()
    def handler(signum, _):
        call_soon(queue._add, signum, idempotent=True)
    with _signal_handler(signals, handler):
        yield queue
