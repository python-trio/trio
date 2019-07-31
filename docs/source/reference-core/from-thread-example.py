import trio


def thread_fn(receive_from_trio, send_to_trio):
    while True:
        # Since we're in a thread, we can't call methods on Trio
        # objects directly -- so we use trio.from_thread to call them.
        try:
            request = trio.from_thread.run(receive_from_trio.receive)
        except trio.EndOfChannel:
            trio.from_thread.run(send_to_trio.aclose)
            return
        else:
            response = request + 1
            trio.from_thread.run(send_to_trio.send, response)


async def main():
    send_to_thread, receive_from_trio = trio.open_memory_channel(0)
    send_to_trio, receive_from_thread = trio.open_memory_channel(0)

    async with trio.open_nursery() as nursery:
        # In a background thread, run:
        #   thread_fn(portal, receive_from_trio, send_to_trio)
        nursery.start_soon(
            trio.to_thread.run_sync, thread_fn, receive_from_trio, send_to_trio
        )

        # prints "1"
        await send_to_thread.send(0)
        print(await receive_from_thread.receive())

        # prints "2"
        await send_to_thread.send(1)
        print(await receive_from_thread.receive())

        # When we close the channel, it signals the thread to exit.
        await send_to_thread.aclose()

        # When we exit the nursery, it waits for the background thread to
        # exit.


trio.run(main)
