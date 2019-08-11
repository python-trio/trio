import threading
import queue as stdlib_queue
from itertools import count

import attr
import outcome

import trio

from ._sync import CapacityLimiter
from ._core import enable_ki_protection, disable_ki_protection, RunVar, TrioToken

# Global due to Threading API, thread local storage for trio token
TOKEN_LOCAL = threading.local()


class BlockingTrioPortal:
    def __init__(self, trio_token=None):
        if trio_token is None:
            trio_token = trio.hazmat.current_trio_token()
        self._trio_token = trio_token

    def run(self, afn, *args):
        return from_thread_run(afn, *args, trio_token=self._trio_token)

    def run_sync(self, fn, *args):
        return from_thread_run_sync(fn, *args, trio_token=self._trio_token)


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

_limiter_local = RunVar("limiter")
# I pulled this number out of the air; it isn't based on anything. Probably we
# should make some kind of measurements to pick a good value.
DEFAULT_LIMIT = 40
_thread_counter = count()


def current_default_thread_limiter():
    """Get the default `~trio.CapacityLimiter` used by
    `trio.to_thread.run_sync`.

    The most common reason to call this would be if you want to modify its
    :attr:`~trio.CapacityLimiter.total_tokens` attribute.

    """
    try:
        limiter = _limiter_local.get()
    except LookupError:
        limiter = CapacityLimiter(DEFAULT_LIMIT)
        _limiter_local.set(limiter)
    return limiter


# Eventually we might build this into a full-fledged deadlock-detection
# system; see https://github.com/python-trio/trio/issues/182
# But for now we just need an object to stand in for the thread, so we can
# keep track of who's holding the CapacityLimiter's token.
@attr.s(frozen=True, cmp=False, hash=False)
class ThreadPlaceholder:
    name = attr.ib()


@enable_ki_protection
async def to_thread_run_sync(sync_fn, *args, cancellable=False, limiter=None):
    """Convert a blocking operation into an async operation using a thread.

    These two lines are equivalent::

        sync_fn(*args)
        await trio.to_thread.run_sync(sync_fn, *args)

    except that if ``sync_fn`` takes a long time, then the first line will
    block the Trio loop while it runs, while the second line allows other Trio
    tasks to continue working while ``sync_fn`` runs. This is accomplished by
    pushing the call to ``sync_fn(*args)`` off into a worker thread.

    From inside the worker thread, you can get back into Trio using the
    functions in `trio.from_thread`.

    Args:
      sync_fn: An arbitrary synchronous callable.
      *args: Positional arguments to pass to sync_fn. If you need keyword
          arguments, use :func:`functools.partial`.
      cancellable (bool): Whether to allow cancellation of this operation. See
          discussion below.
      limiter (None, or CapacityLimiter-like object):
          An object used to limit the number of simultaneous threads. Most
          commonly this will be a `~trio.CapacityLimiter`, but it could be
          anything providing compatible
          :meth:`~trio.CapacityLimiter.acquire_on_behalf_of` and
          :meth:`~trio.CapacityLimiter.release_on_behalf_of` methods. This
          function will call ``acquire_on_behalf_of`` before starting the
          thread, and ``release_on_behalf_of`` after the thread has finished.

          If None (the default), uses the default `~trio.CapacityLimiter`, as
          returned by :func:`current_default_thread_limiter`.

    **Cancellation handling**: Cancellation is a tricky issue here, because
    neither Python nor the operating systems it runs on provide any general
    mechanism for cancelling an arbitrary synchronous function running in a
    thread. This function will always check for cancellation on entry, before
    starting the thread. But once the thread is running, there are two ways it
    can handle being cancelled:

    * If ``cancellable=False``, the function ignores the cancellation and
      keeps going, just like if we had called ``sync_fn`` synchronously. This
      is the default behavior.

    * If ``cancellable=True``, then this function immediately raises
      `~trio.Cancelled`. In this case **the thread keeps running in
      background** – we just abandon it to do whatever it's going to do, and
      silently discard any return value or errors that it raises. Only use
      this if you know that the operation is safe and side-effect free. (For
      example: :func:`trio.socket.getaddrinfo` is uses a thread with
      ``cancellable=True``, because it doesn't really affect anything if a
      stray hostname lookup keeps running in the background.)

      The ``limiter`` is only released after the thread has *actually*
      finished – which in the case of cancellation may be some time after this
      function has returned. If :func:`trio.run` finishes before the thread
      does, then the limiter release method will never be called at all.

    .. warning::

       You should not use this function to call long-running CPU-bound
       functions! In addition to the usual GIL-related reasons why using
       threads for CPU-bound work is not very effective in Python, there is an
       additional problem: on CPython, `CPU-bound threads tend to "starve out"
       IO-bound threads <https://bugs.python.org/issue7946>`__, so using
       threads for CPU-bound work is likely to adversely affect the main
       thread running Trio. If you need to do this, you're better off using a
       worker process, or perhaps PyPy (which still has a GIL, but may do a
       better job of fairly allocating CPU time between threads).

    Returns:
      Whatever ``sync_fn(*args)`` returns.

    Raises:
      Exception: Whatever ``sync_fn(*args)`` raises.

    """
    await trio.hazmat.checkpoint_if_cancelled()
    token = trio.hazmat.current_trio_token()
    if limiter is None:
        limiter = current_default_thread_limiter()

    # Holds a reference to the task that's blocked in this function waiting
    # for the result – or None if this function was cancelled and we should
    # discard the result.
    task_register = [trio.hazmat.current_task()]
    name = "trio-worker-{}".format(next(_thread_counter))
    placeholder = ThreadPlaceholder(name)

    # This function gets scheduled into the Trio run loop to deliver the
    # thread's result.
    def report_back_in_trio_thread_fn(result):
        def do_release_then_return_result():
            # release_on_behalf_of is an arbitrary user-defined method, so it
            # might raise an error. If it does, we want that error to
            # replace the regular return value, and if the regular return was
            # already an exception then we want them to chain.
            try:
                return result.unwrap()
            finally:
                limiter.release_on_behalf_of(placeholder)

        result = outcome.capture(do_release_then_return_result)
        if task_register[0] is not None:
            trio.hazmat.reschedule(task_register[0], result)

    # This is the function that runs in the worker thread to do the actual
    # work and then schedule the call to report_back_in_trio_thread_fn
    # Since this is spawned in a new thread, the trio token needs to be passed
    # explicitly to it so it can inject it into thread local storage
    def worker_thread_fn(trio_token):
        TOKEN_LOCAL.token = trio_token
        try:
            result = outcome.capture(sync_fn, *args)
            try:
                token.run_sync_soon(report_back_in_trio_thread_fn, result)
            except trio.RunFinishedError:
                # The entire run finished, so our particular task is certainly
                # long gone -- it must have cancelled.
                pass
        finally:
            del TOKEN_LOCAL.token

    await limiter.acquire_on_behalf_of(placeholder)
    try:
        # daemon=True because it might get left behind if we cancel, and in
        # this case shouldn't block process exit.
        current_trio_token = trio.hazmat.current_trio_token()
        thread = threading.Thread(
            target=worker_thread_fn,
            args=(current_trio_token,),
            name=name,
            daemon=True
        )
        thread.start()
    except:
        limiter.release_on_behalf_of(placeholder)
        raise

    def abort(_):
        if cancellable:
            task_register[0] = None
            return trio.hazmat.Abort.SUCCEEDED
        else:
            return trio.hazmat.Abort.FAILED

    return await trio.hazmat.wait_task_rescheduled(abort)


def _run_fn_as_system_task(cb, fn, *args, trio_token=None):
    """Helper function for from_thread.run and from_thread.run_sync.

    Since this internally uses TrioToken.run_sync_soon, all warnings about
    raised exceptions canceling all tasks should be noted.
    """

    if trio_token and not isinstance(trio_token, TrioToken):
        raise RuntimeError("Passed kwarg trio_token is not of type TrioToken")

    if not trio_token:
        try:
            trio_token = TOKEN_LOCAL.token
        except AttributeError:
            raise RuntimeError(
                "this thread wasn't created by Trio, pass kwarg trio_token=..."
            )

    # TODO: This is only necessary for compatibility with BlockingTrioPortal.
    # once that is deprecated, this check should no longer be necessary because
    # thread local storage (or the absence of) is sufficient to check if trio
    # is running in a thread or not.
    try:
        trio.hazmat.current_task()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "this is a blocking function; call it from a thread"
        )

    q = stdlib_queue.Queue()
    trio_token.run_sync_soon(cb, q, fn, args)
    return q.get().unwrap()


def from_thread_run(afn, *args, trio_token=None):
    """Run the given async function in the parent Trio thread, blocking until it
    is complete.

    Returns:
      Whatever ``afn(*args)`` returns.

    Returns or raises whatever the given function returns or raises. It
    can also raise exceptions of its own:

    Raises:
        RunFinishedError: if the corresponding call to :func:`trio.run` has
            already completed.
        Cancelled: if the corresponding call to :func:`trio.run` completes
            while ``afn(*args)`` is running, then ``afn`` is likely to raise
            :exc:`trio.Cancelled`, and this will propagate out into
        RuntimeError: if you try calling this from inside the Trio thread,
            which would otherwise cause a deadlock.
        AttributeError: if no ``trio_token`` was provided, and we can't infer
            one from context.

    **Locating a Trio Token**: There are two ways to specify which
    `trio.run` loop to reenter:

        - Spawn this thread from `trio.to_thread.run_sync`. Trio will
          automatically capture the relevant Trio token and use it when you
          want to re-enter Trio.
        - Pass a keyword argument, ``trio_token`` specifiying a specific
          `trio.run` loop to re-enter. This is useful in case you have a
          "foreign" thread, spawned using some other framework, and still want
          to enter Trio.
    """

    def callback(q, afn, args):
        @disable_ki_protection
        async def unprotected_afn():
            return await afn(*args)

        async def await_in_trio_thread_task():
            q.put_nowait(await outcome.acapture(unprotected_afn))

        trio.hazmat.spawn_system_task(await_in_trio_thread_task, name=afn)

    return _run_fn_as_system_task(callback, afn, *args, trio_token=trio_token)


def from_thread_run_sync(fn, *args, trio_token=None):
    """Run the given sync function in the parent Trio thread, blocking until it
    is complete.

    Returns:
      Whatever ``fn(*args)`` returns.

    Returns or raises whatever the given function returns or raises. It
    can also raise exceptions of its own:

    Raises:
        RunFinishedError: if the corresponding call to `trio.run` has
            already completed.
        Cancelled: if the corresponding call to `trio.run` completes
            while ``afn(*args)`` is running, then ``afn`` is likely to raise
            :exc:`trio.Cancelled`, and this will propagate out into
        RuntimeError: if you try calling this from inside the Trio thread,
            which would otherwise cause a deadlock.
        AttributeError: if no ``trio_token`` was provided, and we can't infer
            one from context.

    **Locating a Trio Token**: There are two ways to specify which
    `trio.run` loop to reenter:

        - Spawn this thread from `trio.to_thread.run_sync`. Trio will
          automatically capture the relevant Trio token and use it when you
          want to re-enter Trio.
        - Pass a keyword argument, ``trio_token`` specifiying a specific
          `trio.run` loop to re-enter. This is useful in case you have a
          "foreign" thread, spawned using some other framework, and still want
          to enter Trio.
    """

    def callback(q, fn, args):
        @disable_ki_protection
        def unprotected_fn():
            return fn(*args)

        res = outcome.capture(unprotected_fn)
        q.put_nowait(res)

    return _run_fn_as_system_task(callback, fn, *args, trio_token=trio_token)
