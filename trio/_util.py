import sys
from functools import wraps

import async_generator

__all__ = ["aitercompat", "acontextmanager"]

# Decorator to handle the change to __aiter__ in 3.5.2
def aiter_compat(aiter_impl):
    if sys.version_info < (3, 5, 2):
        @wraps(aiter_impl)
        async def __aiter__(*args, **kwargs):
            return aiter_impl(*args, **kwargs)
        return __aiter__
    else:
        return aiter_impl

# Very much derived from the one in contextlib, by copy/pasting and then
# asyncifying everything.
# So this is a derivative work licensed under the PSF License, which requires
# the following notice:
#
# Copyright © 2001-2017 Python Software Foundation; All Rights Reserved
class _AsyncGeneratorContextManager:
    def __init__(self, func, args, kwds):
        self._agen = func(*args, **kwds).__aiter__()

    async def __aenter__(self):
        if sys.version_info < (3, 5, 2):
            self._agen = await self._agen
        try:
            return await self._agen.asend(None)
        except StopAsyncIteration:
            raise RuntimeError("async generator didn't yield") from None

    async def __aexit__(self, type, value, traceback):
        if type is None:
            try:
                await self._agen.asend(None)
            except StopAsyncIteration:
                return
            else:
                raise RuntimeError("async generator didn't stop")
        else:
            if value is None:
                # Need to force instantiation so we can reliably
                # tell if we get the same exception back
                value = type()
            try:
                await self._agen.athrow(type, value, traceback)
                raise RuntimeError("async generator didn't stop after athrow()")
            except StopAsyncIteration as exc:
                # Suppress StopIteration *unless* it's the same exception that
                # was passed to throw().  This prevents a StopIteration
                # raised inside the "with" statement from being suppressed.
                return (exc is not value)
            except RuntimeError as exc:
                # Don't re-raise the passed in exception. (issue27112)
                if exc is value:
                    return False
                # Likewise, avoid suppressing if a StopIteration exception
                # was passed to throw() and later wrapped into a RuntimeError
                # (see PEP 479).
                if exc.__cause__ is value:
                    return False
                raise
            except:
                # only re-raise if it's *not* the exception that was
                # passed to throw(), because __exit__() must not raise
                # an exception unless __exit__() itself failed.  But throw()
                # has to raise the exception to signal propagation, so this
                # fixes the impedance mismatch between the throw() protocol
                # and the __exit__() protocol.
                #
                if sys.exc_info()[1] is not value:
                    raise

def acontextmanager(func):
    """Like @contextmanager, but async."""
    if not async_generator.isasyncgenfunction(func):
        raise TypeError(
            "must be an async generator (native or from async_generator; "
            "if using @async_generator then @acontextmanager must be on top.")
    @wraps(func)
    def helper(*args, **kwds):
        return _AsyncGeneratorContextManager(func, args, kwds)
    return helper
