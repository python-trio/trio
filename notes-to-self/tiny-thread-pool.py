# This is some very messy notes on how we might implement a thread cache

import threading
import Queue

# idea:
#
# unbounded thread pool; tracks how many threads are "available" and how much
# work there is to do; if work > available threads, spawn a new thread
#
# if a thread sits idle for >N ms, exit
#
# we don't need to support job cancellation
#
# we do need to mark a thread as "available" just before it
# signals back to Trio that it's done, to maintain the invariant that all
# unavailable threads are inside the limiter= protection
#
# maintaining this invariant while exiting can be a bit tricky
#
# maybe a simple target should be to always have 1 idle thread

# XX we can't use a single shared dispatch queue, because we need LIFO
# scheduling, or else the idle-thread timeout won't work!
#
# instead, keep a list/deque/OrderedDict/something of idle threads, and
# dispatch by popping one off; put things back by pushing them on the end
# maybe one shared dispatch Lock, plus a Condition for each thread
# dispatch by dropping the job into the place where the thread can see it and
# then signalling its Condition? or could have separate locks

@attr.s(frozen=True)
class Job:
    main = attr.ib()
    main_args = attr.ib()
    finish = attr.ib()
    finish_args = attr.ib()

class EXIT:
    pass

class ThreadCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._idle_workers = deque()
        self._closed = False

    def close(self):
        self._closed = True
        with self._lock:
            while self._idle_workers:
                self._idle_workers.pop().submit(None)

    def submit(self, job):
        with self._lock:
            if not self._idle_workers:
                WorkerThread(self, self._lock, job)
            else:
                worker = self._idle_workers.pop()
                worker.submit(job)

    # Called from another thread
    # Must be called with the lock held
    def remove_idle_worker(self, worker):
        self._idle_workers.remove(worker)

    # Called from another thread
    # Lock is *not* held
    def add_idle_worker(self, worker):
        if self._closed:
            with self._lock:
            worker.submit
        self._idle_workers.append(worker)

# XX thread name

IDLE_TIMEOUT = 1.0

class WorkerThread:
    def __init__(self, cache, lock, initial_job):
        self._cache = cache
        self._condition = threading.Condition(lock)
        self._job = None
        self._thread = threading.Thread(
            target=self._loop, args=(initial_job,), daemon=True)
        self._thread.start()

    # Must be called with the lock held
    def submit(self, job):
        assert self._job is None
        self._job = job
        self._condition.notify()

    def _loop(self, initial_job):
        self._run_job(initial_job)
        while True:
            with self._condition:
                self._condition.wait(IDLE_TIMEOUT):
                job = self._job
                self._job = None
                if job is None:
                    self._cache.remove_idle_worker(self)
                    return
            # Dropped the lock, and have a job to do
            self._run_job(job)

    def _run_job(self, job):
        job.main(*job.main_args)
        self._cache.add_idle_worker(self)
        job.finish(*job.finish_args)


# Probably the interface should be: trio.hazmat.call_soon_in_worker_thread?

# Enqueueing work:
#   put into unbounded queue
#   with lock:
#       if idle_threads:
#           idle_threads -= 1
#       else:
#           spawn a new thread (it starts out non-idle)
#
# Thread shutdown:
#   with lock:
#       idle_threads -= 1
#       check for work one last time, and then either exit or do it
#
# Thread startup:
#
# check for work
# while True:
#   mark self as idle
#   check for work (with timeout)
#   either do work or shutdown

# if we want to support QueueUserAPC cancellation, we need a way to get back
# the thread id... maybe that just works like
#
# def WaitForSingleObjectEx_thread_fn(...):
#   with lock:
#     check if already cancelled
#     put our thread id where main thread can find it
#   WaitForSingleObjectEx(...)
