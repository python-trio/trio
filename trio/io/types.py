from functools import partial

import trio


def _method_factory(cls, meth_name):
    async def wrapper(self, *args, **kwargs):
        meth = getattr(self._file, meth_name)
        func = partial(meth, *args, **kwargs)
        return await trio.run_in_worker_thread(func)

    wrapper.__name__ = meth_name
    wrapper.__qualname__ = '.'.join((__name__,
                                     cls.__name__,
                                     meth_name))
    return wrapper


class AsyncIOType(type):
    def __init__(cls, name, bases, attrs):
        super().__init__(name, bases, attrs)

        for meth_name in cls._wrap:
            wrapper = _method_factory(cls, meth_name)
            setattr(cls, meth_name, wrapper)


class AsyncIOBase(metaclass=AsyncIOType):
    _forward = ['readable', 'writable', 'seekable', 'isatty',
                'closed', 'fileno']

    _wrap = ['close', 'flush', 'readline', 'readlines', 'tell',
             'writelines', 'seek', 'truncate']

    def __init__(self, file):
        self._file = file

    def __getattr__(self, name):
        if name in self._forward:
            return getattr(self._file, name)
        raise AttributeError(name)

    def __dir__(self):
        return super().__dir__() + list(self._forward)

    async def __aiter__(self):
        return self

    async def __anext__(self):
        line = await self.readline()
        if line:
            return line
        else:
            return StopAsyncIteration

    async def __aenter__(self):
        return self

    async def __aexit__(self, typ, value, traceback):
        return await self.close()


class AsyncRawIOBase(AsyncIOBase):
    _wrap = ['read', 'readall', 'readinto', 'write']


class AsyncBufferedIOBase(AsyncIOBase):
    _wrap = ['readinto', 'detach', 'read', 'read1', 'write']


class AsyncTextIOBase(AsyncIOBase):
    _forward = AsyncIOBase._forward + \
               ['encoding', 'errors', 'newlines']

    _wrap = ['detach', 'read', 'readline', 'write']
