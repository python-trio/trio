# across-realtime.py

import time
import trio
import trio.testing

YEAR = 365 * 24 * 60 * 60  # seconds


async def task1():
    start = trio.current_time()

    print("task1: sleeping for 1 year")
    await trio.sleep(YEAR)

    duration = trio.current_time() - start
    print(f"task1: woke up; clock says I've slept {duration / YEAR} years")

    print("task1: sleeping for 1 year, 100 times")
    for _ in range(100):
        await trio.sleep(YEAR)

    duration = trio.current_time() - start
    print(f"task1: slept {duration / YEAR} years total")


async def task2():
    start = trio.current_time()

    print("task2: sleeping for 5 years")
    await trio.sleep(5 * YEAR)

    duration = trio.current_time() - start
    print(f"task2: woke up; clock says I've slept {duration / YEAR} years")

    print("task2: sleeping for 500 years")
    await trio.sleep(500 * YEAR)

    duration = trio.current_time() - start
    print(f"task2: slept {duration / YEAR} years total")


async def main():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(task1)
        nursery.start_soon(task2)


def run_example(clock):
    real_start = time.perf_counter()
    trio.run(main, clock=clock)
    real_duration = time.perf_counter() - real_start
    print(f"Total real time elapsed: {real_duration} seconds")


print("Clock where time passes at 100 years per second:\n")
run_example(trio.testing.MockClock(rate=100 * YEAR))

print("\nClock where time automatically skips past the boring parts:\n")
run_example(trio.testing.MockClock(autojump_threshold=0))
