import trio


async def foo() -> int:
    print("in foo!")
    return 3


print("running!")
print(trio.run(foo))
