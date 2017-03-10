import sys
import trio

(COUNT_STR,) = sys.argv[1:]
COUNT = int(COUNT_STR)

async def main():
    async with trio.open_nursery() as nursery:
        for _ in range(COUNT):
            nursery.spawn(trio.sleep, 1)

trio.run(main)
