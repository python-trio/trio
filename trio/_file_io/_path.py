from functools import wraps, update_wrapper
import os
import types
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath, PosixPath, WindowsPath

from trio._file_io._helpers import thread_wrapper_factory, getattr_factory, copy_metadata


__all__ = ['AsyncPath', 'AsyncPosixPath', 'AsyncWindowsPath']


def _forward_factory(cls, attr_name, attr):
    @wraps(attr)
    def wrapper(self, *args, **kwargs):
        attr = getattr(self._wrapped, attr_name)
        value = attr(*args, **kwargs)
        if isinstance(value, cls._forwards):
            # re-wrap methods that return new paths
            value = cls._from_path(value)
        return value

    return wrapper


def _wrapper_factory(cls, attr_name):
    wrapped = thread_wrapper_factory(cls, attr_name)

    @wraps(wrapped)
    async def wrapper(self, *args, **kwargs):
        value = await wrapped(self, *args, **kwargs)
        if isinstance(value, cls._wraps):
            value = cls._from_path(value)
        return value

    return wrapper


class AsyncAutoWrapperType(type):
    def __init__(cls, name, bases, attrs):
        super().__init__(name, bases, attrs)
        # only initialize the superclass
        if bases:
            return

        forward = []
        # forward functions of _forwards
        for attr_name, attr in cls._forwards.__dict__.items():
            if attr_name.startswith('_') or attr_name in attrs:
                continue

            if isinstance(attr, property):
                forward.append(attr_name)
            elif isinstance(attr, types.FunctionType):
                wrapper = _forward_factory(cls, attr_name, attr)
                setattr(cls, attr_name, wrapper)
            else:
                raise TypeError(attr_name, type(attr))

        setattr(cls, '__getattr__', getattr_factory(cls, forward))

        # generate wrappers for functions of _wraps
        for attr_name, attr in cls._wraps.__dict__.items():
            if attr_name.startswith('_') or attr_name in attrs:
                continue

            if isinstance(attr, classmethod):
                setattr(cls, attr_name, attr)
            elif isinstance(attr, types.FunctionType):
                wrapper = _wrapper_factory(cls, attr_name)
                setattr(cls, attr_name, wrapper)
            else:
                raise TypeError(attr_name, type(attr))


class AsyncPath(metaclass=AsyncAutoWrapperType):
    _wraps = Path
    _forwards = PurePath

    def __new__(cls, *args, **kwargs):
        path = Path(*args, **kwargs)

        self = cls._from_path(path)
        return self

    @classmethod
    def _from_path(cls, path):
        if isinstance(path, PosixPath):
            cls = AsyncPosixPath
        elif isinstance(path, WindowsPath):
            cls = AsyncWindowsPath
        else:
            raise TypeError(type(path))

        self = object.__new__(cls)
        self._wrapped = path
        return self

    def __fspath__(self):
        return self._wrapped.__fspath__()


os.PathLike.register(AsyncPath)


class AsyncPosixPath(AsyncPath):
    __slots__ = ()


class AsyncWindowsPath(AsyncPath):
    __slots__ = ()
