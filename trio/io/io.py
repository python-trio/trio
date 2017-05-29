from functools import singledispatch, wraps
import io

import trio
from trio.io import types


__all__ = ['open', 'wrap']


class AsyncGeneratorContextManager:
    def __init__(self, gen):
        self.gen = gen

    async def __aenter__(self):
        return await self.gen.__anext__()

    async def __aexit__(self, typ, value, traceback):
        try:
            await self.gen.__anext__()
        except StopAsyncIteration:
            return
        raise RuntimeError("generator didn't stop")


def async_generator_context(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return AsyncGeneratorContextManager(func(*args, **kwargs))
    return wrapper


@async_generator_context
async def open(file, mode='r', buffering=-1, encoding=None, errors=None,
               newline=None, closefd=True, opener=None):
    try:
        file = wrap(await trio.run_in_worker_thread(io.open, file))
        yield file
    finally:
        await file.close()


@singledispatch
def wrap(file):
    raise TypeError(file)


@wrap.register(io._io._TextIOBase)
def _(file):
    return types.AsyncTextIOBase(file)


@wrap.register(io._io._BufferedIOBase)
def _(file):
    return types.AsyncBufferedIOBase(file)


@wrap.register(io._io._RawIOBase)
def _(file):
    return types.AsyncRawIOBase(file)
