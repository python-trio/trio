# Little script to measure how wait_readable scales with the number of
# sockets. We look at three key measurements:
#
# - cost of issuing wait_readable
# - cost of running the scheduler, while wait_readables are blocked in the
#   background
# - cost of cancelling wait_readable
#
# On Linux and macOS, these all appear to be ~O(1), as we'd expect.
#
# On Windows: with the old 'select'-based loop, the cost of scheduling grew
# with the number of outstanding sockets, which was bad.
#
# To run this on Unix systems, you'll probably first have to run:
#
#   ulimit -n 31000
#
# or similar.

import time
import trio
import trio.testing
import socket

async def main():
    for total in [10, 100, 500, 1_000, 10_000, 20_000, 30_000]:
        def pt(desc, *, count=total, item="socket"):
            nonlocal last_time
            now = time.perf_counter()
            total_ms = (now - last_time) * 1000
            per_us = total_ms * 1000 / count
            print(f"{desc}: {total_ms:.2f} ms total, {per_us:.2f} µs/{item}")
            last_time = now

        print(f"\n-- {total} sockets --")
        last_time = time.perf_counter()
        sockets = []
        for _ in range(total // 2):
            a, b = socket.socketpair()
            sockets += [a, b]
        pt("socket creation")
        async with trio.open_nursery() as nursery:
            for s in sockets:
                nursery.start_soon(trio.lowlevel.wait_readable, s)
            await trio.testing.wait_all_tasks_blocked()
            pt("spawning wait tasks")
            for _ in range(1000):
                await trio.lowlevel.cancel_shielded_checkpoint()
            pt("scheduling 1000 times", count=1000, item="schedule")
            nursery.cancel_scope.cancel()
        pt("cancelling wait tasks")
        for sock in sockets:
            sock.close()
        pt("closing sockets")

trio.run(main)
