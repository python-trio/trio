# This example usually crashes!

import trio
import random

async def main():
    async with trio.open_nursery() as nursery:
        send_channel, receive_channel = trio.open_memory_channel(0)
        # Start two producers
        nursery.start_soon(producer, "A", send_channel)
        nursery.start_soon(producer, "B", send_channel)
        # And two consumers
        nursery.start_soon(consumer, "X", receive_channel)
        nursery.start_soon(consumer, "Y", receive_channel)

async def producer(name, send_channel):
    async with send_channel:
        for i in range(3):
            await send_channel.send("{} from producer {}".format(i, name))
            # Random sleeps help trigger the problem more reliably
            await trio.sleep(random.random())

async def consumer(name, receive_channel):
    async with receive_channel:
        async for value in receive_channel:
            print("consumer {} got value {!r}".format(name, value))
            # Random sleeps help trigger the problem more reliably
            await trio.sleep(random.random())

trio.run(main)
