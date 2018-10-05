# Little script to get a rough estimate of how much memory each task takes

import resource
import trio
import trio.testing

LOW = 1000
HIGH = 10000

async def tinytask():
    await trio.sleep_forever()

async def measure(count):
    async with trio.open_nursery() as nursery:
        for _ in range(count):
            nursery.start_soon(tinytask)
        await trio.testing.wait_all_tasks_blocked()
        nursery.cancel_scope.cancel()
        return resource.getrusage(resource.RUSAGE_SELF)


async def main():
    low_usage = await measure(LOW)
    high_usage = await measure(HIGH + LOW)

    print("Memory usage per task:",
          (high_usage.ru_maxrss - low_usage.ru_maxrss) / HIGH)
    print("(kilobytes on Linux, bytes on macOS)")

trio.run(main)
