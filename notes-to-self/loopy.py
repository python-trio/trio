import trio
import time

async def loopy():
    try:
        while True:
            time.sleep(0.01)
            await trio.sleep(0)
    except KeyboardInterrupt:
        print("KI!")

async def main():
    await trio.spawn(loopy)
    await trio.spawn(loopy)
    await trio.spawn(loopy)

trio.run(main)
