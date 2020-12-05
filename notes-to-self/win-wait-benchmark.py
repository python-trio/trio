# WaitForSingleObject is how Trio interacts with Windows synchronization objects.
# https://docs.microsoft.com/en-us/windows/win32/sync/synchronization-objects
# Oddly, these objects cannot interact with the overlapped IO APIs and therefore
# can't be merged in with the rest of the IOCP waiting in _io_windows.
#
# By far the most common use case for this (and the only one within Trio) is
# waiting on process handles especially Process.aclose. So that is absolutely
# an important case to optimize for, using one or up to a few dozen at a time.
#
# Another use case which could potentially use this is watching for filesystem
# changes with Find{First|Next}ChangeNotification and reacting to that. This
# could have any number of required handles depending on the filter setup.
#
# The original simple implementation uses to_thread.run_sync and
# WaitForMultipleObjects to wait on the object and an extra Trio-owned Event
# object used purely for cancel. This has the benefit of being low maintenance
# and constructed of high-level APIs, but it also spawns a thread per handle, so
# the change notification application could quickly create many, many threads.
#
# WaitForMultipleObjects can wait for up to MAXIMUM_WAIT_OBJECTS = 64 objects.
# This means windows imposes O(n) thread/memory scaling on object waits, but at
# least we can improve things by a factor of ~64, and the Process application
# will never need more than one thread.
#
# There are many possible solutions to pooling object waits this way. This
# script compares them by speed, latency, thread, and memory usage from 1 to 1k
# events under several contrived benchmark/stress test usage patterns.
