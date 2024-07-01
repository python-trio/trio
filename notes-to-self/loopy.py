import time

import trio


async def loopy():
    try:
        while True:
            # synchronous sleep to avoid maxing out CPU
            time.sleep(0.01)  # noqa: ASYNC251
            await trio.lowlevel.checkpoint()
    except KeyboardInterrupt:
        print("KI!")


async def main():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(loopy)
        nursery.start_soon(loopy)
        nursery.start_soon(loopy)


trio.run(main)
