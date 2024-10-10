import sys
from typing import NoReturn

import trio

sys.stderr = sys.stdout


async def child1() -> NoReturn:
    raise ValueError


async def child2() -> None:
    async with trio.open_nursery() as nursery:
        nursery.start_soon(grandchild1)
        nursery.start_soon(grandchild2)


async def grandchild1() -> NoReturn:
    raise KeyError


async def grandchild2() -> NoReturn:
    raise NameError("Bob")


async def main() -> None:
    async with trio.open_nursery() as nursery:
        nursery.start_soon(child1)
        nursery.start_soon(child2)
        # nursery.start_soon(grandchild1)


trio.run(main)
