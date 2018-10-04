import trio

async def main():
    async with trio.open_nursery() as nursery:
        # Open a channel:
        send_channel, receive_channel = trio.open_memory_channel(0)
        # Start a producer and a consumer, passing one end of the channel to
        # each of them:
        nursery.start_soon(producer, send_channel)
        nursery.start_soon(consumer, receive_channel)

async def producer(send_channel):
    # Producer sends 3 messages
    for i in range(3):
        # The producer sends using 'await send_channel.send(...)'
        await send_channel.send("message {}".format(i))

async def consumer(receive_channel):
    # The consumer uses an 'async for' loop to receive the values:
    async for value in receive_channel:
        print("got value {!r}".format(value))

trio.run(main)
