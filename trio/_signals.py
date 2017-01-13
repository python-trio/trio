import signal
from contextlib import contextmanager

from . import Queue

# When we add signal handling for real:
# - on Windows signals kind of don't exist?
# - on Linux signalfd is the natural way. It acts as an *alternative* signal
# delivery mechanism. The way you use it is to mask out the relevant signals
# process-wide (so that they don't get delivered the normal way), and then
# when you read from signalfd that actually counts as delivering it (despite
# the mask). If we do this we'll need to coordinate the mask stuff between
# different watchers and with the mask stuff above. This works from any thread
# though!
# - on MacOS/*BSD, kqueue is the natural way. It acts as an *additional*
# signal delivery mechanism. Signals are delivered the normal way, *and* are
# delivered to kqueue. So you want to set them to SIG_IGN so that they don't
# end up pending forever (I guess?). I can't find any actual docs on how
# masking and EVFILT_SIGNAL interact. I did see someone note that if a signal
# is pending when the kqueue filter is added then you *don't* get notified of
# that, which makes sense. ...unfortunately I think this means that we can
# only do this from the main thread?

# tentatively: stick with the annoying old signal-handler based way of doing
# things and only allow it on the main thread. once we have
# call_soon_threadsafe that does most of the work.

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

# XX this doesn't work at all currently
# need to revive call_soon_threadsafe I guess (very very hazmat!) with the
# same bounded-work rule, and then convert run_in_main_thread to run off of
# that.
# or.... signals can generate tons of redundant work if a bunch arrive at
# once. Maybe just make signal handling be
#   add signal to some set
#   wakeup
# and have the wakeup task process both?
# ...but how do we get it to the right queue then :-/
@contextmanager
def catch_signals(signals):
    call_soon_threadsafe = current_call_soon_threadsafe_func()
    queue = Queue()
    def handler(signum, _):
        call_soon_threadsafe(queue.put_nowait, signum)
    with _signal_handler(signals, handler):
        yield queue
