import trio

from functools import wraps, partial


def async_wraps(cls, attr_name):
    def decorator(func):
        func.__name__ = attr_name
        func.__qualname__ = '.'.join((cls.__qualname__,
                                      attr_name))
        return func
    return decorator


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
