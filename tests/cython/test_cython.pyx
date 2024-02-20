# cython: language_level=3
import trio

# the output of the prints are not currently checked, we only check
# if the program can be compiled and doesn't crash when run.

# The content of the program can easily be extended if there's other behaviour
# that might be likely to be problematic for cython.
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

trio.run(trio_main)
