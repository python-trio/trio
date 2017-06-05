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
        return await trio.run_in_worker_thread(func)

    return wrapper


def getattr_factory(cls, forward):
    def __getattr__(self, name):
        if name in forward:
            return getattr(self._wrapped, name)
        raise AttributeError(name)
    return __getattr__
