# cython: language_level=3
import trio

async def foo() -> None:
    print('.')

async def trio_main() -> None:
    print('hello...')
    await trio.sleep(1)
    print(' world !')

    async with trio.open_nursery() as nursery:
        nursery.start_soon(foo)
        nursery.start_soon(foo)
        nursery.start_soon(foo)

def main() -> None:
    trio.run(trio_main)

main()
