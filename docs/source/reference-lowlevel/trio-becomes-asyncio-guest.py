import asyncio, trio

# This is a drop-in replacement for asyncio.run(), except that you call
# it from a Trio program instead of from synchronous Python.
async def asyncio_run_from_trio(coro):
    aio_task = None
    raise_cancel = None

    # run_child_host() is one of two functions you must write to adapt
    # become_guest_for() to a particular host loop setup.
    # Its job is to start the host loop, and call resume_trio_as_guest()
    # as soon as the host loop is able to accept callbacks.
    # resume_trio_as_guest() takes the same keyword arguments
    # run_sync_soon_threadsafe= (required) and
    # run_sync_soon_not_threadsafe= (optional)
    # that you would use with start_guest_run().
    def run_child_host(resume_trio_as_guest):
        async def aio_bootstrap():
            # Save the top-level task so we can cancel it
            nonlocal aio_task
            aio_task = asyncio.current_task()

            # Resume running Trio code
            loop = asyncio.get_running_loop()
            resume_trio_as_guest(
                run_sync_soon_threadsafe=loop.call_soon_threadsafe,
                run_sync_soon_not_threadsafe=loop.call_soon,
            )

            # Run the asyncio coroutine we were given
            try:
                return await coro
            except asyncio.CancelledError:
                # If this cancellation was requested by Trio, then
                # raise_cancel will be non-None and we should call it
                # to raise whatever exception Trio wants to raise.
                # Otherwise, the cancellation was requested within
                # asyncio (like 'asyncio.current_task().cancel()') and
                # we should let it continue to be represented with an
                # asyncio exception.
                if raise_cancel is not None:
                    raise_cancel()
                raise

        return asyncio.run(aio_bootstrap())

    # deliver_cancel() is the other one. It gets called when Trio
    # wants to cancel the call to become_guest_for() (e.g., because
    # the whole Trio run is shutting down due to a Ctrl+C).
    # Its job is to get run_child_host() to return soon.
    # Ideally, it should make run_child_host() call raise_cancel()
    # to raise a trio.Cancelled exception, so that the cancel scope's
    # cancelled_caught member accurately reflects whether anything
    # was interrupted. If all you care about is Ctrl+C working, though,
    # just stopping the host loop is sufficient.
    def deliver_cancel(incoming_raise_cancel):
        # This won't be called until after resume_trio_as_guest() happens,
        # so we can rely on aio_task being non-None.
        nonlocal raise_cancel
        raise_cancel = incoming_raise_cancel
        aio_task.cancel()

    # Once you have those two, it's just:
    return await trio.lowlevel.become_guest_for(run_child_host, deliver_cancel)

# The rest of this is a demo of how to use it.

# A tiny asyncio program
async def asyncio_main():
    for i in range(5):
        print("Hello from asyncio!")
        # This is inside asyncio, so we have to use asyncio APIs
        await asyncio.sleep(1)
    return "asyncio done!"

# A simple Trio function to demonstrate that Trio code continues
# to run while the asyncio loop is running
async def trio_reminder_task():
    await trio.sleep(0.5)
    while True:
        print("Trio is still running")
        await trio.sleep(1)

# The code to run asyncio_main and trio_reminder_task in parallel
async def trio_main():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(trio_reminder_task)
        aio_result = await asyncio_run_from_trio(asyncio_main())
        print("asyncio program is done, with result:", aio_result)
        nursery.cancel_scope.cancel()  # stop the trio_reminder_task

trio.run(trio_main)
