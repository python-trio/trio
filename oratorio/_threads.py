# WorkerThread for pushing

# call_soon_threadsafe()
# exceptions here panic the taskrunner

# in_main_thread() -- captures the oratorio thread, runs directly if that's us,
# otherwise sets up a condition variable, runs in main thread, passes result
# back, unwraps result
#
# I guess this might be overkill for the obvious implementing-Queue type of
# cases, given that they're just flipping a bit or whatever in the main thread
# that causes a task to be rescheduled "eventually"
# OTOH it does at least guarantee that there's somewhere for exceptions to go!
