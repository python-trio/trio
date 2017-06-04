from functools import wraps
import io

import trio
from trio.io import types


__all__ = ['open_file', 'wrap_file']


class ClosingContextManager:
    def __init__(self, coro):
        self._coro = coro
        self._wrapper = None

    async def __aenter__(self):
        self._wrapper = await self._coro
        return self._wrapper

    async def __aexit__(self, typ, value, traceback):
        await self._wrapper.close()

    def __await__(self):
        return self._coro.__await__()


def closing(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return ClosingContextManager(func(*args, **kwargs))
    return wrapper


@closing
async def open_file(file, mode='r', buffering=-1, encoding=None, errors=None,
                    newline=None, closefd=True, opener=None):
    """Asynchronous version of :func:`~io.open`.

    Returns:
        An :term:`asynchronous file object` wrapped in an :term:`asynchronous context manager`.

    Example::

        async with trio.io.open_file(filename) as f:
            async for line in f:
                pass

        assert f.closed

    """
    _file = wrap_file(await trio.run_in_worker_thread(io.open, file, mode,
                                                      buffering, encoding, errors, newline, closefd, opener))
    return _file


def wrap_file(file):
    """This wraps any file-like object in an equivalent asynchronous file-like
    object.

    Args:
        file: a :term:`file object`

    Returns:
        An :term:`asynchronous file object`

    Example::

        f = StringIO('asdf')
        async_f = wrap_file(f)

        assert await async_f.read() == 'asdf'

    """

    if isinstance(file, io.TextIOBase):
        return types.AsyncTextIOBase(file)
    if isinstance(file, io.BufferedIOBase):
        return types.AsyncBufferedIOBase(file)
    if isinstance(file, io.RawIOBase):
        return types.AsyncRawIOBase(file)
    if isinstance(file, io.IOBase):
        return types.AsyncIOBase(file)

    raise TypeError(file)
