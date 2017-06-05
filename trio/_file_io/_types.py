from functools import partial

import trio
from trio import _core
from trio._util import aiter_compat
from trio._file_io._helpers import thread_wrapper_factory


__all__ = ['AsyncRawIOBase', 'AsyncBufferedIOBase', 'AsyncTextIOBase',
           'AsyncIOBase']


class AsyncWrapperType(type):
    def __init__(cls, name, bases, attrs):
        super().__init__(name, bases, attrs)

        for meth_name in cls._wrap:
            wrapper = thread_wrapper_factory(cls, meth_name)
            setattr(cls, meth_name, wrapper)


class AsyncIOBase(metaclass=AsyncWrapperType):
    _forward = ['readable', 'writable', 'seekable', 'isatty',
                'closed', 'fileno']

    _wrap = ['flush', 'readline', 'readlines', 'tell',
             'writelines', 'seek', 'truncate']

    def __init__(self, file):
        self._wrapped = file

    def __getattr__(self, name):
        if name in self._forward:
            return getattr(self._wrapped, name)
        raise AttributeError(name)

    def __dir__(self):
        return super().__dir__() + list(self._forward)

    @aiter_compat
    def __aiter__(self):
        return self

    async def __anext__(self):
        line = await self.readline()
        if line:
            return line
        else:
            raise StopAsyncIteration

    async def __aenter__(self):
        return self

    async def __aexit__(self, typ, value, traceback):
        await self.close()

    async def close(self):
        # ensure the underling file is closed during cancellation
        with _core.open_cancel_scope(shield=True):
            await trio.run_in_worker_thread(self._wrapped.close)

        await _core.yield_if_cancelled()


class AsyncRawIOBase(AsyncIOBase):
    _wrap = ['read', 'readall', 'readinto', 'write']


class AsyncBufferedIOBase(AsyncIOBase):
    _wrap = ['readinto', 'detach', 'read', 'read1', 'write']


class AsyncTextIOBase(AsyncIOBase):
    _forward = AsyncIOBase._forward + \
               ['encoding', 'errors', 'newlines']

    _wrap = ['detach', 'read', 'readline', 'write']
