import signal
from contextlib import contextmanager

# For now, this just has a little convenience thing to let us mask out SIGINT
# while inside the task runner guts

if hasattr(signal, "pthread_sigmask"):
    @contextmanager
    def sigmask(self, how, mask):
        original = signal.pthread_sigmask(how, mask)
        try:
            yield original
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, original)
else:
    @contextmanager
    def sigmask(self, how, mask):
        yield []

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
