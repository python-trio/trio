import pytest
import threading
from queue import Queue
import time
import sys

from .tutil import slow, gc_collect_harder
from .. import _thread_cache
from .._thread_cache import start_thread_soon, ThreadCache, kill_this_thread


def test_thread_cache_basics():
    q = Queue()

    def fn():
        raise RuntimeError("hi")

    def deliver(outcome):
        q.put(outcome)

    start_thread_soon(fn, deliver)

    outcome = q.get()
    with pytest.raises(RuntimeError, match="hi"):
        outcome.unwrap()


def test_thread_cache_deref():
    res = [False]

    class del_me:
        def __call__(self):
            return 42

        def __del__(self):
            res[0] = True

    q = Queue()

    def deliver(outcome):
        q.put(outcome)

    start_thread_soon(del_me(), deliver)
    outcome = q.get()
    assert outcome.unwrap() == 42

    gc_collect_harder()
    assert res[0]


@slow
def test_spawning_new_thread_from_deliver_reuses_starting_thread():
    # We know that no-one else is using the thread cache, so if we keep
    # submitting new jobs the instant the previous one is finished, we should
    # keep getting the same thread over and over. This tests both that the
    # thread cache is LIFO, and that threads can be assigned new work *before*
    # deliver exits.

    # Make sure there are a few threads running, so if we weren't LIFO then we
    # could grab the wrong one.
    q = Queue()
    COUNT = 5
    for _ in range(COUNT):
        start_thread_soon(lambda: time.sleep(1), lambda result: q.put(result))
    for _ in range(COUNT):
        q.get().unwrap()

    seen_threads = set()
    done = threading.Event()

    def deliver(n, _):
        print(n)
        seen_threads.add(threading.current_thread())
        if n == 0:
            done.set()
        else:
            start_thread_soon(lambda: None, lambda _: deliver(n - 1, _))

    start_thread_soon(lambda: None, lambda _: deliver(5, _))

    done.wait()

    assert len(seen_threads) == 1


@slow
def test_idle_threads_exit(monkeypatch):
    # Temporarily set the idle timeout to something tiny, to speed up the
    # test. (But non-zero, so that the worker loop will at least yield the
    # CPU.)
    monkeypatch.setattr(_thread_cache, "IDLE_TIMEOUT", 0.0001)

    q = Queue()
    start_thread_soon(lambda: None, lambda _: q.put(threading.current_thread()))
    seen_thread = q.get()
    # Since the idle timeout is 0, after sleeping for 1 second, the thread
    # should have exited
    time.sleep(1)
    assert not seen_thread.is_alive()


def test_race_between_idle_exit_and_job_assignment(monkeypatch):
    # This is a lock where the first few times you try to acquire it with a
    # timeout, it waits until the lock is available and then pretends to time
    # out. Using this in our thread cache implementation causes the following
    # sequence:
    #
    # 1. start_thread_soon grabs the worker thread, assigns it a job, and
    #    releases its lock.
    # 2. The worker thread wakes up (because the lock has been released), but
    #    the JankyLock lies to it and tells it that the lock timed out. So the
    #    worker thread tries to exit.
    # 3. The worker thread checks for the race between exiting and being
    #    assigned a job, and discovers that it *is* in the process of being
    #    assigned a job, so it loops around and tries to acquire the lock
    #    again.
    # 4. Eventually the JankyLock admits that the lock is available, and
    #    everything proceeds as normal.

    class JankyLock:
        def __init__(self):
            self._lock = threading.Lock()
            self._counter = 3

        def acquire(self, timeout=None):
            self._lock.acquire()
            if timeout is None:
                return True
            else:
                if self._counter > 0:
                    self._counter -= 1
                    self._lock.release()
                    return False
                return True

        def release(self):
            self._lock.release()

    monkeypatch.setattr(_thread_cache, "Lock", JankyLock)

    tc = ThreadCache()
    done = threading.Event()
    tc.start_thread_soon(lambda: None, lambda _: done.set())
    done.wait()
    # Let's kill the thread we started, so it doesn't hang around until the
    # test suite finishes. Doesn't really do any harm, but it can be confusing
    # to see it in debug output. This is hacky, and leaves our ThreadCache
    # object in an inconsistent state... but it doesn't matter, because we're
    # not going to use it again anyway.
    tc.start_thread_soon(lambda: None, lambda _: kill_this_thread())
