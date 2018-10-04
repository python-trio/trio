import trio

async def main():
    async with trio.open_nursery() as nursery:
        send_channel, receive_channel = trio.open_memory_channel(0)
        nursery.start_soon(producer, send_channel)
        nursery.start_soon(consumer, receive_channel)

async def producer(send_channel):
    async with send_channel:
        for i in range(3):
            await send_channel.send("message {}".format(i))

async def consumer(receive_channel):
    async with receive_channel:
        async for value in receive_channel:
            print("got value {!r}".format(value))

trio.run(main)
