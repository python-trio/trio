from functools import wraps, partial
import os
import types
import pathlib

import trio
from trio._util import async_wraps


__all__ = ['Path']


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
    @async_wraps(cls, pathlib.Path, meth_name)
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
        type(cls).generate_forwards(cls, attrs)
        type(cls).generate_wraps(cls, attrs)
        type(cls).generate_magic(cls, attrs)

    def generate_forwards(cls, attrs):
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

    def generate_wraps(cls, attrs):
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

    def generate_magic(cls, attrs):
        # generate wrappers for magic
        for attr_name in cls._forward_magic:
            attr = getattr(cls._forwards, attr_name)
            wrapper = _forward_factory(cls, attr_name, attr)
            setattr(cls, attr_name, wrapper)


class Path(metaclass=AsyncAutoWrapperType):
    """A :class:`~pathlib.Path` wrapper that executes non-computational Path methods in
    :meth:`trio.run_in_worker_thread`.

    """

    _wraps = pathlib.Path
    _forwards = pathlib.PurePath
    _forward_magic = [
        '__str__', '__bytes__',
        '__eq__', '__lt__', '__le__', '__gt__', '__ge__'
    ]

    def __init__(self, *args, **kwargs):
        self._wrapped = pathlib.Path(*args, **kwargs)

    def __getattr__(self, name):
        if name in self._forward:
            return getattr(self._wrapped, name)
        raise AttributeError(name)

    def __dir__(self):
        return super().__dir__() + self._forward

    def __repr__(self):
        return 'trio.Path({})'.format(str(self))

    def __fspath__(self):
        try:
            return self._wrapped.__fspath__()
        # python3.5 compat
        except AttributeError:  # pragma: no cover
            return str(self)

    @classmethod
    def _from_wrapped(cls, wrapped):
        self = object.__new__(cls)
        self._wrapped = wrapped
        return self

    async def open(self, *args, **kwargs):
        func = partial(self._wrapped.open, *args, **kwargs)
        value = await trio.run_in_worker_thread(func)
        return trio.wrap_file(value)


# not documented upstream
delattr(Path.absolute, '__doc__')


# python3.5 compat
if hasattr(os, 'PathLike'):  # pragma: no cover
    os.PathLike.register(Path)
