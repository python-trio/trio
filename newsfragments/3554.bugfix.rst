When an ``async with`` on an `@as_safe_channel <trio.as_safe_channel>` generator is cancelled
while the generator's own code is running, the generator's `~trio.Cancelled` now propagates, as
it would from a plain ``async for``. Previously the choice was random, so an exception the
generator raised before its cleanup was cancelled could be missing from the traceback.
