import threading
import queue as stdlib_queue
from itertools import count

from . import _core

__all__ = [
    "current_await_in_trio_thread", "current_run_in_trio_thread",
    "run_in_worker_thread",
]

def _await_in_trio_thread_cb(q, afn, args):
    async def await_in_trio_thread_task():
        nonlocal afn
        afn = _core.disable_ki_protection(afn)
        q.put_nowait(await _core.Result.acapture(afn, *args))
    _core.spawn_system_task(await_in_trio_thread_task)

def _run_in_trio_thread_cb(q, fn, args):
    fn = _core.disable_ki_protection(fn)
    q.put_nowait(_core.Result.capture(fn, *args))

def _current_do_in_trio_thread(name, cb):
    call_soon = _core.current_call_soon_thread_and_signal_safe()
    trio_thread = threading.current_thread()
    def do_in_trio_thread(fn, *args):
        if threading.current_thread() == trio_thread:
            raise RuntimeError("must be called from a thread")
        q = stdlib_queue.Queue()
        call_soon(cb, q, fn, args)
        return q.get().unwrap()
    do_in_trio_thread.__name__ = name
    return do_in_trio_thread

def current_run_in_trio_thread():
    return _current_do_in_trio_thread(
        "run_in_trio_thread", _run_in_trio_thread_cb)

def current_await_in_trio_thread():
    return _current_do_in_trio_thread(
        "await_in_trio_thread", _await_in_trio_thread_cb)

################################################################

# XX at some point it probably makes sense to implement some sort of thread
# pool? Or at least that's what everyone says.
#
# There are two arguments for thread pools:
# - speed (re-using threads instead of starting new ones)
# - throttling (if you have 1000 tasks, queue them up instead of spawning 1000
#   threads and running out of memory)
#
# Regarding speed, it's not clear how much of an advantage this is. Some
# numbers on my Linux laptop:
#
# Spawning and then joining a thread:
#
# In [25]: %timeit t = threading.Thread(target=lambda: None); t.start(); t.join()
# 10000 loops, best of 3: 44 µs per loop
#
# Using a thread pool:
#
# In [26]: tpp = concurrent.futures.ThreadPoolExecutor()
# In [27]: %timeit tpp.submit(lambda: None).result()
# <warm up run elided>
# In [28]: %timeit tpp.submit(lambda: None).result()
# 10000 loops, best of 3: 40.8 µs per loop
#
# What's a fast getaddrinfo look like?
#
# # with hot DNS cache:
# In [23]: %timeit socket.getaddrinfo("google.com", "80")
# 10 loops, best of 3: 50.9 ms per loop
#
# In [29]: %timeit socket.getaddrinfo("127.0.0.1", "80")
# 100000 loops, best of 3: 9.73 µs per loop
#
#
# So... maybe we can beat concurrent.futures with a super-efficient thread
# pool or something, but there really is not a lot of headroom here.
#
# Of course other systems might be different... here's CPython 3.6 in a
# Virtualbox VM running Windows 10 on that same Linux laptop:
#
# In [13]: %timeit t = threading.Thread(target=lambda: None); t.start(); t.join()
# 10000 loops, best of 3: 127 µs per loop
#
# In [18]: %timeit tpp.submit(lambda: None).result()
# 10000 loops, best of 3: 31.9 µs per loop
#
# So on Windows there *might* be an advantage? You've gotta be doing a lot of
# connections, with very fast DNS indeed, for that 100 us to matter. But maybe
# someone is.
#
#
# Regarding throttling: this is very much a trade-off. On the one hand, you
# don't want to overwhelm the machine, obviously. On the other hand, queueing
# up work on a central thread-pool creates a central coordination point which
# can potentially create deadlocks and all kinds of fun things. This is very
# context dependent. For getaddrinfo, whatever, they'll make progress and
# complete (we hope), and you want to throttle them to some reasonable
# amount. For calling waitpid() (because just say no to SIGCHLD), then you
# really want one thread-per-waitpid(), because for all you know the user has
# written some ridiculous thing like:
#
#   for p in processes:
#       await spawn(p.wait)
#   # Deadlock here if there are enough processes:
#   await some_other_subprocess.wait()
#   for p in processes:
#       p.terminate()
#
# This goes doubly for the sort of wacky thread usage we see in curio.abide
# (though, I'm not sure if that's actually useful in practice in our context,
# run_in_trio_thread seems like it might be a nicer synchronization primitive
# for most uses than trying to make threading.Lock awaitable).
#
# See also this very relevant discussion:
#
#   https://twistedmatrix.com/trac/ticket/5298
#
# "Interacting with the products at Rackspace which use Twisted, I've seen
# problems caused by thread-pool maximum sizes with some annoying
# regularity. The basic problem is this: if you have a hard limit on the
# number of threads, *it is not possible to write a correct program which may
# require starting a new thread to un-block a blocked pool thread*" - glyph
#
# For now, if we want to throttle getaddrinfo I think the simplest thing is
# for the socket code to have a semaphore for getaddrinfo calls.
#
# Regarding the memory overhead of threads, in theory one should be able to
# reduce this a *lot* for a thread that's just calling getaddrinfo or
# (especially) waitpid. Windows and pthreads both offer the ability to set
# thread stack size on a thread-by-thread basis. Unfortunately as of 3.6
# CPython doesn't expose this in a useful way (all you can do is set it
# globally for the whole process, so it's - ironically - not thread safe).
#
# (It's also unclear how much stack size actually matters; on a 64-bit Linux
# server with overcommit -- i.e., the most common configuration -- then AFAICT
# really the only real limit is on stack size actually *used*; how much you
# *allocate* should be pretty much irrelevant.)

_worker_thread_counter = count()

@_core.enable_ki_protection
async def run_in_worker_thread(fn, *args, cancellable=False):
    await _core.yield_if_cancelled()
    call_soon = _core.current_call_soon_thread_and_signal_safe()
    task_register = [_core.current_task()]
    def trio_thread_fn(result):
        if task_register[0] is not None:
            _core.reschedule(task_register[0], result)
    def worker_thread_fn():
        result = _core.Result.capture(fn, *args)
        try:
            call_soon(trio_thread_fn, result)
        except _core.RunFinishedError:
            # The entire run finished, so our particular task is certainly
            # long gone -- it must have cancelled.
            pass
    name = "trio-worker-{}".format(next(_worker_thread_counter))
    # daemonic because it might get left behind if we cancel
    thread = threading.Thread(target=worker_thread_fn, name=name, daemon=True)
    thread.start()
    def abort(_):
        if cancellable:
            task_register[0] = None
            return _core.Abort.SUCCEEDED
        else:
            return _core.Abort.FAILED
    return await _core.yield_indefinitely(abort)
