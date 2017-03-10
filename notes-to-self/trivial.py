import trio

async def foo():
    print("in foo!")
    return 3

print("running!")
print(trio.run(foo))
