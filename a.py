from contextlib import AsyncExitStack, asynccontextmanager
# import trio_asyncio
import trio

@asynccontextmanager
async def yielder():
    try:
        await trio.sleep(0)
        yield None
    finally:
        print("exiting from yielder")
        await trio.sleep(3)
        print("done exiting from yielder")

class Context:
    def __init__(self):
        self._stack = AsyncExitStack()
        self.nursery = None
    async def __aenter__(self):
        async with AsyncExitStack() as stack:
            self.nursery = await stack.enter_async_context(trio.open_nursery())
            await stack.enter_async_context(yielder())
            self.nursery.start_soon(some_async_fn)
            self._stack = stack.pop_all()
        return self
    
    async def __aexit__(self, *exc):
        with trio.CancelScope(shield=True):
            await self._stack.__aexit__(*exc)


async def some_async_fn():
    raise RuntimeError()

@asynccontextmanager
async def ContextF():
    try:
        async with trio.open_nursery() as nursery, yielder():
            nursery.start_soon(some_async_fn)
            yield
    finally:
        print("exiting from contextf")
        await trio.sleep(3)
        print("done exiting from contextf")

async def main2():
    async with Context() as context:
        pass
    
trio.run(main2)