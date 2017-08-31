import sys
import trio

sys.stderr = sys.stdout

async def child1():
    raise ValueError

async def child2():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(grandchild1)
        nursery.start_soon(grandchild2)

async def grandchild1():
    raise KeyError

async def grandchild2():
    raise NameError("Bob")

async def main():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(child1)
        nursery.start_soon(child2)
        #nursery.start_soon(grandchild1)

trio.run(main)
