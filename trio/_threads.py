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
    _core.spawn_system_task(await_in_trio_thread_task, name=afn)

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
async def run_in_worker_thread(sync_fn, *args, cancellable=False):
    """Convert a blocking operation in an async operation using a thread.

    These two lines are equivalent::

        sync_fn(*args)
        await run_in_worker_thread(sync_fn, *args)

    except that if ``sync_fn`` takes a long time, then the first line will
    block the Trio loop while it runs, while the second line allows other Trio
    tasks to continue working while ``sync_fn`` runs. This is accomplished by
    pushing the call to ``sync_fn(*args)`` off into a worker thread.

    **Cancellation handling**: Cancellation is a tricky issue here, because
    neither Python nor the operating systems it runs on provide any general
    way to communicate with an arbitrary synchronous function running in a
    thread and tell it to stop. This function will always check for
    cancellation on entry, before starting the thread. But once the thread is
    running, there are two ways it can handle being cancelled:

    * If ``cancellable=False``, the function ignores the cancellation and
      keeps going, just like if we had called ``sync_fn`` synchronously. This
      is the default behavior.

    * If ``cancellable=True``, then ``run_in_worker_thread`` immediately
      raises :exc:`Cancelled`. In this case **the thread keeps running in
      background** – we just abandon it to do whatever it's going to do, and
      silently discard any return value or errors that it raises. Only use
      this if you know that the operation is safe and side-effect free. (For
      example: ``trio.socket.getaddrinfo`` is implemented using
      :func:`run_in_worker_thread`, and it sets ``cancellable=True`` because
      it doesn't really matter if a stray hostname lookup keeps running in the
      background.)

    .. warning::

       You should not use :func:`run_in_worker_thread` to call CPU-bound
       functions! In addition to the usual GIL-related reasons why using
       threads for CPU-bound work is not very effective in Python, there is an
       additional problem: on CPython, `CPU-bound threads tend to "starve out"
       IO-bound threads <https://bugs.python.org/issue7946>`__, so using
       :func:`run_in_worker_thread` for CPU-bound work is likely to adversely
       affect the main thread running trio. If you need to do this, you're
       better off using a worker process, or perhaps PyPy (which still has a
       GIL, but may do a better job of fairly allocating CPU time between
       threads).

    Args:
      sync_fn: An arbitrary synchronous callable.
      *args: Positional arguments to pass to sync_fn. If you need keyword
          arguments, use :func:`functools.partial`.
      cancellable (bool): Whether to allow cancellation of this operation. See
          discussion above.

    Returns:
      Whatever ``sync_fn`` returns.

    Raises:
      Whatever ``sync_fn`` raises.

    """
    await _core.yield_if_cancelled()
    call_soon = _core.current_call_soon_thread_and_signal_safe()
    task_register = [_core.current_task()]
    def trio_thread_fn(result):
        if task_register[0] is not None:
            _core.reschedule(task_register[0], result)
    def worker_thread_fn():
        result = _core.Result.capture(sync_fn, *args)
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
