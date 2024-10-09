import trio


async def foo():  # noqa: RUF029  # await not used
    print("in foo!")
    return 3


print("running!")
print(trio.run(foo))
