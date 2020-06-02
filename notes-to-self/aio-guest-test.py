import asyncio
import trio

async def aio_main():
    loop = asyncio.get_running_loop()

    trio_done_fut = asyncio.Future()
    def trio_done_callback(main_outcome):
        print(f"trio_main finished: {main_outcome!r}")
        trio_done_fut.set_result(main_outcome)

    trio.lowlevel.start_guest_run(
        trio_main,
        run_sync_soon_threadsafe=loop.call_soon_threadsafe,
        done_callback=trio_done_callback,
    )

    (await trio_done_fut).unwrap()


async def trio_main():
    print("trio_main!")

    to_trio, from_aio = trio.open_memory_channel(float("inf"))
    from_trio = asyncio.Queue()

    asyncio.create_task(aio_pingpong(from_trio, to_trio))

    from_trio.put_nowait(0)

    async for n in from_aio:
        print(f"trio got: {n}")
        await trio.sleep(1)
        from_trio.put_nowait(n + 1)
        if n >= 10:
            return

async def aio_pingpong(from_trio, to_trio):
    print("aio_pingpong!")

    while True:
        n = await from_trio.get()
        print(f"aio got: {n}")
        await asyncio.sleep(1)
        to_trio.send_nowait(n + 1)


asyncio.run(aio_main())
