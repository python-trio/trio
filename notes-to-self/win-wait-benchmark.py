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
# script compares them by speed, latency, thread, and memory usage from 100
# to 10000 events under several contrived benchmark/stress test usage patterns.

from concurrent.futures import ThreadPoolExecutor
from itertools import repeat
from multiprocessing.spawn import freeze_support

import trio, trio.testing, trio._wait_for_object
import time
import multiprocessing

from trio._core._windows_cffi import ffi, raise_winerror
from trio._wait_for_object import (
    _no_pool,
    _win32_pool,
    _pool_per_run,
    _pool_per_process,
)

ffi.cdef(
    """
  HANDLE GetCurrentProcess();
  
  typedef struct _PROCESS_MEMORY_COUNTERS {
  DWORD  cb;
  DWORD  PageFaultCount;
  SIZE_T PeakWorkingSetSize;
  SIZE_T WorkingSetSize;
  SIZE_T QuotaPeakPagedPoolUsage;
  SIZE_T QuotaPagedPoolUsage;
  SIZE_T QuotaPeakNonPagedPoolUsage;
  SIZE_T QuotaNonPagedPoolUsage;
  SIZE_T PagefileUsage;
  SIZE_T PeakPagefileUsage;
} PROCESS_MEMORY_COUNTERS, *PPROCESS_MEMORY_COUNTERS; 
 
  BOOL K32GetProcessMemoryInfo (
  HANDLE                   Process,
  PPROCESS_MEMORY_COUNTERS ppsmemCounters,
  DWORD                    cb
);"""
)
kernel32 = ffi.dlopen("kernel32.dll")


def proc_inner(q, fn, args):
    stats = fn(*args)
    q.put(stats)


def time_with_proc(fn, *args):
    q = multiprocessing.SimpleQueue()
    proc = multiprocessing.Process(target=proc_inner, args=(q, fn, args), daemon=True)
    proc.start()
    stats = q.get()
    proc.join()
    return stats


def one_handle_n_tasks(setup_pool_fn, m, n):
    setup_pool_fn()
    handle = kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL)
    dts = []
    ppmc = ffi.new("PPROCESS_MEMORY_COUNTERS")
    proc_handle = kernel32.GetCurrentProcess()

    async def wait_task(sequence):
        t0 = time.perf_counter()
        async with trio.open_nursery() as nursery:
            for _ in sequence:
                nursery.start_soon(trio._wait_for_object.WaitForSingleObject, handle)
                await trio.lowlevel.checkpoint()
            await trio.testing.wait_all_tasks_blocked()
            kernel32.SetEvent(handle)
        dts.append(time.perf_counter() - t0)

    multirun(m, wait_task, range(n))
    kernel32.CloseHandle(handle)
    if not kernel32.K32GetProcessMemoryInfo(
        proc_handle, ppmc, ffi.sizeof("PROCESS_MEMORY_COUNTERS")
    ):
        raise_winerror()
    memory = ppmc[0].PeakWorkingSetSize // 1_000_000
    threads = len(trio._core._thread_cache.THREAD_CACHE._idle_workers)
    latency = 0
    return round(sum(dts), 3), latency, threads, memory


def n_handles(setup_pool_fn, m, n):
    setup_pool_fn()
    handles = [kernel32.CreateEventA(ffi.NULL, True, False, ffi.NULL) for _ in range(n)]
    dts = []
    ppmc = ffi.new("PPROCESS_MEMORY_COUNTERS")
    proc_handle = kernel32.GetCurrentProcess()

    async def wait_task(handles):
        t0 = time.perf_counter()
        async with trio.open_nursery() as nursery:
            for handle in handles:
                nursery.start_soon(trio._wait_for_object.WaitForSingleObject, handle)
                await trio.lowlevel.checkpoint()
            await trio.testing.wait_all_tasks_blocked()
            for handle in handles:
                kernel32.SetEvent(handle)
        dts.append((time.perf_counter() - t0))

    multirun(m, wait_task, handles)
    for handle in handles:
        kernel32.CloseHandle(handle)
    if not kernel32.K32GetProcessMemoryInfo(
        proc_handle, ppmc, ffi.sizeof("PROCESS_MEMORY_COUNTERS")
    ):
        raise_winerror()
    memory = ppmc[0].PeakWorkingSetSize // 1_000_000
    threads = len(trio._core._thread_cache.THREAD_CACHE._idle_workers)
    latency = 0
    return round(sum(dts), 3), latency, threads, memory


def multirun(num_runs, async_fn, sequence):
    executor = ThreadPoolExecutor(num_runs)
    n = len(sequence) // num_runs
    list(
        executor.map(
            trio.run,
            repeat(async_fn),
            (sequence[i : i + n] for i in range(0, len(sequence), n)),
        )
    )


def multi_bench(setup_pool_fn, num_runs, num_waits):
    print(setup_pool_fn)
    out = []
    for m in num_runs:
        for n in num_waits:
            task_scaling = time_with_proc(one_handle_n_tasks, setup_pool_fn, m, n)
            handle_scaling = time_with_proc(n_handles, setup_pool_fn, m, n)
            print((m, n, task_scaling, handle_scaling))
            out.append((m, n, task_scaling, handle_scaling))


if __name__ == "__main__":
    freeze_support()
    n = [100, 200, 500, 1000, 2000, 5000]
    m = [1, 2, 5, 10]
    multi_bench(_no_pool, m, n)
    multi_bench(_win32_pool, m, n)
    multi_bench(_pool_per_run, m, n)
    multi_bench(_pool_per_process, m, n)
