import trio

from functools import wraps, partial


def async_wraps(cls, wrapped_cls, attr_name):
    def decorator(func):
        func.__name__ = attr_name
        func.__qualname__ = '.'.join((cls.__qualname__,
                                      attr_name))

        func.__doc__ = """Like :meth:`~{}.{}.{}`, but async.

        """.format(wrapped_cls.__module__,
                   wrapped_cls.__qualname__,
                   attr_name)

        return func
    return decorator
