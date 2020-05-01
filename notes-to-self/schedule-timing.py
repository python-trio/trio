import trio
import time

LOOPS = 0
RUNNING = True

async def reschedule_loop(depth):
    if depth == 0:
        global LOOPS
        while RUNNING:
            LOOPS += 1
            await trio.sleep(0)
            #await trio.lowlevel.cancel_shielded_checkpoint()
    else:
        await reschedule_loop(depth - 1)

async def report_loop():
    global RUNNING
    try:
        while True:
            start_count = LOOPS
            start_time = time.perf_counter()
            await trio.sleep(1)
            end_time = time.perf_counter()
            end_count = LOOPS
            loops = end_count - start_count
            duration = end_time - start_time
            print("{} loops/sec".format(loops / duration))
    finally:
        RUNNING = False

async def main():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(reschedule_loop, 10)
        nursery.start_soon(report_loop)

trio.run(main)
