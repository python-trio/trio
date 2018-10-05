# Simulate a producer that generates values 10x faster than the
# consumer can handle them.

import trio
import math

async def producer(send_channel):
    count = 0
    while True:
        # Pretend that we have to do some work to create this message, and it
        # takes 0.1 seconds:
        await trio.sleep(0.1)
        await send_channel.send(count)
        print("Sent message:", count)
        count += 1

async def consumer(receive_channel):
    async for value in receive_channel:
        print("Received message:", value)
        # Pretend that we have to do some work to handle this message, and it
        # takes 1 second
        await trio.sleep(1)

async def main():
    send_channel, receive_channel = trio.open_memory_channel(math.inf)
    async with trio.open_nursery() as nursery:
        nursery.start_soon(producer, send_channel)
        nursery.start_soon(consumer, receive_channel)

trio.run(main)
