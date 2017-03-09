import os
import sys
import signal
import threading
from contextlib import contextmanager

from . import _core
from ._util import aiter_compat
from ._sync import Semaphore, Event

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

# Equivalent to the C function raise(), which Python doesn't wrap
if os.name == "nt":
    # On windows, os.kill exists but is really weird.
    #
    # If you give it CTRL_C_EVENT or CTRL_BREAK_EVENT, it tries to deliver
    # those using GenerateConsoleCtrlEvent. But I found that when I tried
    # to run my test normally, it would freeze waiting... unless I added
    # print statements, in which case the test suddenly worked. So I guess
    # these signals are only delivered if/when you access the console? I
    # don't really know what was going on there. From reading the
    # GenerateConsoleCtrlEvent docs I don't know how it worked at all.
    #
    # OTOH, if you pass os.kill any *other* signal number... then CPython
    # just calls TerminateProcess (wtf).
    #
    # So, anyway, os.kill is not so useful for testing purposes. Instead
    # we use raise():
    #
    #   https://msdn.microsoft.com/en-us/library/dwwzkt4c.aspx
    #
    # Have to import cffi inside the 'if os.name' block because we don't
    # depend on cffi on non-Windows platforms. (It would be easy to switch
    # this to ctypes though if we ever remove the cffi dependency.)
    #
    # Some more information:
    #   https://bugs.python.org/issue26350
    #
    # Anyway, we use this for two things:
    # - redelivering unhandled signals
    # - generating synthetic signals for tests
    # and for both of those purposes, 'raise' works fine.
    import cffi
    _ffi = cffi.FFI()
    _ffi.cdef("int raise(int);")
    _lib = _ffi.dlopen("api-ms-win-crt-runtime-l1-1-0.dll")
    _signal_raise = getattr(_lib, "raise")
else:
    def _signal_raise(signum):
        os.kill(os.getpid(), signum)

class SignalQueue:
    def __init__(self):
        self._semaphore = Semaphore(0, max_value=1)
        self._pending = set()
        self._closed = False

    def _add(self, signum):
        if self._closed:
            _signal_raise(signum)
        else:
            if not self._pending:
                self._semaphore.release()
            self._pending.add(signum)

    def _redeliver_remaining(self):
        # First make sure that any signals still in the delivery pipeline will
        # get redelivered
        self._closed = True
        # And then redeliver any that are sitting in pending. This is doen
        # using a weird recursive construct to make sure we process everything
        # even if some of the handlers raise exceptions.
        def deliver_next():
            if self._pending:
                signum = self._pending.pop()
                try:
                    _signal_raise(signum)
                finally:
                    deliver_next()
        deliver_next()

    @aiter_compat
    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._closed:
            raise RuntimeError("catch_signals block exited")
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

    The async iterator blocks until at least one signal has arrived, and then
    yields a :class:`set` containing all of the signals that were received
    since the last iteration. (This is generally similar to how
    :class:`UnboundedQueue` works, but since Unix semantics are that identical
    signals can/should be coalesced, here we use a :class:`set` for storage
    instead of a :class:`list`.)

    Note that if you leave the ``with`` block while the iterator has
    unextracted signals still pending inside it, then they will be
    re-delivered using Python's regular signal handling logic. This avoids a
    race condition when signals arrives just before we exit the ``with``
    block.

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
    try:
        with _signal_handler(signals, handler):
            yield queue
    finally:
        queue._redeliver_remaining()
