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
            #await trio.hazmat.yield_briefly_no_cancel()
    else:
        await reschedule_loop(depth - 1)

async def report_loop():
    global RUNNING
    try:
        while True:
            start_count = LOOPS
            start_time = time.time()
            await trio.sleep(1)
            end_time = time.time()
            end_count = LOOPS
            loops = end_count - start_count
            duration = end_time - start_time
            print("{} loops/sec".format(loops / duration))
    finally:
        RUNNING = False

async def main():
    async with trio.open_nursery() as nursery:
        nursery.spawn(reschedule_loop, 10)
        nursery.spawn(report_loop)

trio.run(main)
