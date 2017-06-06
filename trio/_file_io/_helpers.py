import trio

from functools import wraps, partial


def copy_metadata(func):
    @wraps(func)
    def wrapper(cls, attr_name):
        wrapped = func(cls, attr_name)

        wrapped.__name__ = attr_name
        wrapped.__qualname__ = '.'.join((__name__,
                                         cls.__name__,
                                         attr_name))
        return wrapped
    return wrapper


@copy_metadata
def thread_wrapper_factory(cls, meth_name):
    async def wrapper(self, *args, **kwargs):
        meth = getattr(self._wrapped, meth_name)
        func = partial(meth, *args, **kwargs)
        value = await trio.run_in_worker_thread(func)
        if isinstance(value, cls._wraps):
            value = cls._from_wrapped(value)
        return value

    return wrapper


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
