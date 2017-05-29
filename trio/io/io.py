from functools import singledispatch
import io

import trio
from trio.io import types


__all__ = ['open', 'wrap']


async def open(file, mode='r', buffering=-1, encoding=None, errors=None,
               newline=None, closefd=True, opener=None):
    _file = await trio.run_in_worker_thread(io.open, file)
    return wrap(_file)


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
