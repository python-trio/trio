# Little utilities we use internally

import os
import sys
from functools import wraps

import async_generator

# There's a dependency loop here... _core is allowed to use this file (in fact
# it's the *only* file in the main trio/ package it's allowed to use), but
# UnLock needs yield_briefly so it also has to import _core. Possibly we
# should split this file into two: one for true generic low-level utility
# code, and one for higher level helpers?
from . import _core

__all__ = ["signal_raise", "aiter_compat", "acontextmanager", "UnLock"]

# Equivalent to the C function raise(), which Python doesn't wrap
if os.name == "nt":
    # On windows, os.kill exists but is really weird.
    #
    # If you give it CTRL_C_EVENT or CTRL_BREAK_EVENT, it tries to deliver
    # those using GenerateConsoleCtrlEvent. But I found that when I tried
    # to run my test normally, it would freeze waiting... unless I added
    # print statements, in which case the test suddenly worked. So I guess
    # these signals are only delivered if/when you access the console? I
    # don't really know what was going on there. From reading the
    # GenerateConsoleCtrlEvent docs I don't know how it worked at all.
    #
    # I later spent a bunch of time trying to make GenerateConsoleCtrlEvent
    # work for creating synthetic control-C events, and... failed
    # utterly. There are lots of details in the code and comments
    # removed/added at this commit:
    #     https://github.com/python-trio/trio/commit/95843654173e3e826c34d70a90b369ba6edf2c23
    #
    # OTOH, if you pass os.kill any *other* signal number... then CPython
    # just calls TerminateProcess (wtf).
    #
    # So, anyway, os.kill is not so useful for testing purposes. Instead
    # we use raise():
    #
    #   https://msdn.microsoft.com/en-us/library/dwwzkt4c.aspx
    #
    # Have to import cffi inside the 'if os.name' block because we don't
    # depend on cffi on non-Windows platforms. (It would be easy to switch
    # this to ctypes though if we ever remove the cffi dependency.)
    #
    # Some more information:
    #   https://bugs.python.org/issue26350
    #
    # Anyway, we use this for two things:
    # - redelivering unhandled signals
    # - generating synthetic signals for tests
    # and for both of those purposes, 'raise' works fine.
    import cffi
    _ffi = cffi.FFI()
    _ffi.cdef("int raise(int);")
    _lib = _ffi.dlopen("api-ms-win-crt-runtime-l1-1-0.dll")
    signal_raise = getattr(_lib, "raise")
else:
    def signal_raise(signum):
        os.kill(os.getpid(), signum)


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
# asyncifying everything. (Also I dropped the obscure support for using
# context managers as function decorators. It could be re-added; I just
# couldn't be bothered.)
# So this is a derivative work licensed under the PSF License, which requires
# the following notice:
#
# Copyright © 2001-2017 Python Software Foundation; All Rights Reserved
class _AsyncGeneratorContextManager:
    def __init__(self, func, args, kwds):
        self._func_name = func.__name__
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

    def __enter__(self):
        raise RuntimeError("use 'async with {func_name}(...)', not 'with {func_name}(...)'".format(func_name=self._func_name))

    def __exit__(self):  # pragma: no cover
        assert False, """Never called, but should be defined"""


def acontextmanager(func):
    """Like @contextmanager, but async."""
    if not async_generator.isasyncgenfunction(func):
        raise TypeError(
            "must be an async generator (native or from async_generator; "
            "if using @async_generator then @acontextmanager must be on top.")
    @wraps(func)
    def helper(*args, **kwds):
        return _AsyncGeneratorContextManager(func, args, kwds)
    # A hint for sphinxcontrib-trio:
    helper.__returns_acontextmanager__ = True
    return helper


class _UnLockSync:
    def __init__(self, exc, *args):
        self._exc = exc
        self._args = args
        self._held = False

    def __enter__(self):
        if self._held:
            raise self._exc(*self._args)
        else:
            self._held = True

    def __exit__(self, *args):
        self._held = False


class UnLock:
    """An unnecessary lock.

    Use as an async context manager; if two tasks enter it at the same
    time then the second one raises an error. You can use it when there are
    two pieces of code that *would* collide and need a lock if they ever were
    called at the same time, but that should never happen.

    We use this in particular for things like, making sure that two different
    tasks don't call sendall simultaneously on the same stream.

    This executes a checkpoint on entry. That's the only reason it's async.

    """
    def __init__(self, exc, *args):
        self.sync = _UnLockSync(exc, *args)

    async def __aenter__(self):
        await _core.yield_briefly()
        return self.sync.__enter__()

    async def __aexit__(self, *args):
        return self.sync.__exit__()
