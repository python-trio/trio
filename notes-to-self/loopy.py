import time

import trio


async def loopy():
    try:
        while True:
            time.sleep(  # noqa: ASYNC101  # synchronous sleep to avoid maxing out CPU
                0.01
            )
            await trio.sleep(0)
    except KeyboardInterrupt:
        print("KI!")


async def main():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(loopy)
        nursery.start_soon(loopy)
        nursery.start_soon(loopy)


trio.run(main)
