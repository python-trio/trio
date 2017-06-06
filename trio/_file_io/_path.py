from functools import wraps, partial
import os
import types
from pathlib import Path, PurePath

import trio
from trio._file_io._helpers import async_wraps
from trio._file_io._file_io import closing


__all__ = ['AsyncPath']


def _forward_factory(cls, attr_name, attr):
    @wraps(attr)
    def wrapper(self, *args, **kwargs):
        attr = getattr(self._wrapped, attr_name)
        value = attr(*args, **kwargs)
        if isinstance(value, cls._forwards):
            # re-wrap methods that return new paths
            value = cls._from_wrapped(value)
        return value

    return wrapper


def thread_wrapper_factory(cls, meth_name):
    @async_wraps(cls, Path, meth_name)
    async def wrapper(self, *args, **kwargs):
        meth = getattr(self._wrapped, meth_name)
        func = partial(meth, *args, **kwargs)
        value = await trio.run_in_worker_thread(func)
        if isinstance(value, cls._wraps):
            value = cls._from_wrapped(value)
        return value

    return wrapper


class AsyncAutoWrapperType(type):
    def __init__(cls, name, bases, attrs):
        super().__init__(name, bases, attrs)

        cls._forward = []
        # forward functions of _forwards
        for attr_name, attr in cls._forwards.__dict__.items():
            if attr_name.startswith('_') or attr_name in attrs:
                continue

            if isinstance(attr, property):
                cls._forward.append(attr_name)
            elif isinstance(attr, types.FunctionType):
                wrapper = _forward_factory(cls, attr_name, attr)
                setattr(cls, attr_name, wrapper)
            else:
                raise TypeError(attr_name, type(attr))

        # generate wrappers for functions of _wraps
        for attr_name, attr in cls._wraps.__dict__.items():
            if attr_name.startswith('_') or attr_name in attrs:
                continue

            if isinstance(attr, classmethod):
                setattr(cls, attr_name, attr)
            elif isinstance(attr, types.FunctionType):
                wrapper = thread_wrapper_factory(cls, attr_name)
                setattr(cls, attr_name, wrapper)
            else:
                raise TypeError(attr_name, type(attr))


class AsyncPath(metaclass=AsyncAutoWrapperType):
    _wraps = Path
    _forwards = PurePath

    def __new__(cls, *args, **kwargs):
        path = Path(*args, **kwargs)

        self = cls._from_wrapped(path)
        return self

    def __getattr__(self, name):
        if name in self._forward:
            return getattr(self._wrapped, name)
        raise AttributeError(name)

    def __dir__(self):
        return super().__dir__() + self._forward

    @classmethod
    def _from_wrapped(cls, wrapped):
        self = object.__new__(cls)
        self._wrapped = wrapped
        return self

    def __fspath__(self):
        return self._wrapped.__fspath__()

    @closing
    async def open(self, *args, **kwargs):
        func = partial(self._wrapped.open, *args, **kwargs)
        value = await trio.run_in_worker_thread(func)
        return trio.wrap_file(value)


# python3.5 compat
if hasattr(os, 'PathLike'):
    os.PathLike.register(AsyncPath)
