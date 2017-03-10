import sys
import trio

sys.stderr = sys.stdout

async def child1():
    raise ValueError

async def child2():
    async with trio.open_nursery() as nursery:
        nursery.spawn(grandchild1)
        nursery.spawn(grandchild2)

async def grandchild1():
    raise KeyError

async def grandchild2():
    raise NameError("Bob")

async def main():
    async with trio.open_nursery() as nursery:
        nursery.spawn(child1)
        nursery.spawn(child2)
        #nursery.spawn(grandchild1)

trio.run(main)
