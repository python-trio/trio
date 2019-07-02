# Little utilities we use internally

from abc import ABCMeta
import os
import signal
import sys
import pathlib
from functools import wraps, update_wrapper
import typing as t

import async_generator

# There's a dependency loop here... _core is allowed to use this file (in fact
# it's the *only* file in the main trio/ package it's allowed to use), but
# ConflictDetector needs checkpoint so it also has to import
# _core. Possibly we should split this file into two: one for true generic
# low-level utility code, and one for higher level helpers?

import trio

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
if sys.version_info < (3, 5, 2):

    def aiter_compat(aiter_impl):
        @wraps(aiter_impl)
        async def __aiter__(*args, **kwargs):
            return aiter_impl(*args, **kwargs)

        return __aiter__
else:

    def aiter_compat(aiter_impl):
        return aiter_impl


# See: #461 as to why this is needed.
# The gist is that threading.main_thread() has the capability to lie to us
# if somebody else edits the threading ident cache to replace the main
# thread; causing threading.current_thread() to return a _DummyThread,
# causing the C-c check to fail, and so on.
# Trying to use signal out of the main thread will fail, so we can then
# reliably check if this is the main thread without relying on a
# potentially modified threading.
def is_main_thread():
    """Attempt to reliably check if we are in the main thread."""
    try:
        signal.signal(signal.SIGINT, signal.getsignal(signal.SIGINT))
        return True
    except ValueError:
        return False


class ConflictDetector:
    """Detect when two tasks are about to perform operations that would
    conflict.

    Use as a synchronous context manager; if two tasks enter it at the same
    time then the second one raises an error. You can use it when there are
    two pieces of code that *would* collide and need a lock if they ever were
    called at the same time, but that should never happen.

    We use this in particular for things like, making sure that two different
    tasks don't call sendall simultaneously on the same stream.

    """

    def __init__(self, msg):
        self._msg = msg
        self._held = False

    def __enter__(self):
        if self._held:
            raise trio.BusyResourceError(self._msg)
        else:
            self._held = True

    def __exit__(self, *args):
        self._held = False


def async_wraps(cls, wrapped_cls, attr_name):
    """Similar to wraps, but for async wrappers of non-async functions.

    """

    def decorator(func):
        func.__name__ = attr_name
        func.__qualname__ = '.'.join((cls.__qualname__, attr_name))

        func.__doc__ = """Like :meth:`~{}.{}.{}`, but async.

        """.format(
            wrapped_cls.__module__, wrapped_cls.__qualname__, attr_name
        )

        return func

    return decorator


def fixup_module_metadata(module_name, namespace):
    seen_ids = set()

    def fix_one(obj):
        # avoid infinite recursion (relevant when using
        # typing.Generic, for example)
        if id(obj) in seen_ids:
            return
        seen_ids.add(id(obj))

        mod = getattr(obj, "__module__", None)
        if mod is not None and mod.startswith("trio."):
            obj.__module__ = module_name
            if isinstance(obj, type):
                for attr_value in obj.__dict__.values():
                    fix_one(attr_value)

    for objname, obj in namespace.items():
        if not objname.startswith("_"):  # ignore private attributes
            fix_one(obj)


# os.fspath is defined on Python 3.6+ but we need to support Python 3.5 too
# This is why we provide our own implementation. On Python 3.6+ we use the
# StdLib's version and on Python 3.5 our own version.
# Our own implementation implementation is based on PEP 519 while it has also
# been adapted to work with pathlib objects on python 3.5
# The input typehint is removed as there is no os.PathLike on 3.5.
# See: https://www.python.org/dev/peps/pep-0519/#os


def fspath(path) -> t.Union[str, bytes]:
    """Return the path representation of a path-like object.

    Returns
    -------
    - If str or bytes is passed in, it is returned unchanged.
    - If the os.PathLike interface is implemented it is used to get the path
      representation.
    - If the python version is 3.5 or earlier and a pathlib object is passed,
      the object's string representation is returned.

    Raises
    ------
    - Regardless of the input, if the path representation (e.g. the value
      returned from __fspath__) is not str or bytes, TypeError is raised.
    - If the provided path is not str, bytes, pathlib.PurePath or os.PathLike,
      TypeError is raised.
    """
    if isinstance(path, (str, bytes)):
        return path
    # Work from the object's type to match method resolution of other magic
    # methods.
    path_type = type(path)
    # On python 3.5, pathlib objects don't have the __fspath__ method,
    # but we still want to get their string representation.
    if issubclass(path_type, pathlib.PurePath):
        return str(path)
    try:
        path_repr = path_type.__fspath__(path)
    except AttributeError:
        if hasattr(path_type, '__fspath__'):
            raise
        else:
            raise TypeError(
                "expected str, bytes or os.PathLike object, "
                "not " + path_type.__name__
            )
    if isinstance(path_repr, (str, bytes)):
        return path_repr
    else:
        raise TypeError(
            "expected {}.__fspath__() to return str or bytes, "
            "not {}".format(path_type.__name__,
                            type(path_repr).__name__)
        )


if hasattr(os, "fspath"):
    fspath = os.fspath  # noqa


class generic_function:
    """Decorator that makes a function indexable, to communicate
    non-inferrable generic type parameters to a static type checker.

    If you write::

        @generic_function
        def open_memory_channel(max_buffer_size: int) -> Tuple[
            SendChannel[T], ReceiveChannel[T]
        ]: ...

    it is valid at runtime to say ``open_memory_channel[bytes](5)``.
    This behaves identically to ``open_memory_channel(5)`` at runtime,
    and currently won't type-check without a mypy plugin or clever stubs,
    but at least it becomes possible to write those.
    """

    def __init__(self, fn):
        update_wrapper(self, fn)
        self._fn = fn

    def __call__(self, *args, **kwargs):
        return self._fn(*args, **kwargs)

    def __getitem__(self, _):
        return self


# If a new class inherits from any ABC, then the new class's metaclass has to
# inherit from ABCMeta. If a new class inherits from typing.Generic, and
# you're using Python 3.6 or earlier, then the new class's metaclass has to
# inherit from typing.GenericMeta. Some of the classes that want to use Final
# or NoPublicConstructor inherit from ABCs and generics, so Final has to
# inherit from these metaclasses. Fortunately, GenericMeta inherits from
# ABCMeta, so inheriting from GenericMeta alone is sufficient (when it
# exists at all).
if hasattr(t, "GenericMeta"):
    BaseMeta = t.GenericMeta
else:
    BaseMeta = ABCMeta


class Final(BaseMeta):
    """Metaclass that enforces a class to be final (i.e., subclass not allowed).

    If a class uses this metaclass like this::

        class SomeClass(metaclass=Final):
            pass

    The metaclass will ensure that no sub class can be created.

    Raises
    ------
    - TypeError if a sub class is created
    """

    def __new__(cls, name, bases, cls_namespace):
        for base in bases:
            if isinstance(base, Final):
                raise TypeError(
                    "`%s` does not support subclassing" % base.__name__
                )
        return super().__new__(cls, name, bases, cls_namespace)


class NoPublicConstructor(Final):
    """Metaclass that enforces a class to be final (i.e., subclass not allowed)
    and ensures a private constructor.

    If a class uses this metaclass like this::

        class SomeClass(metaclass=NoPublicConstructor):
            pass

    The metaclass will ensure that no sub class can be created, and that no instance
    can be initialized.

    If you try to instantiate your class (SomeClass()), a TypeError will be thrown.

    Raises
    ------
    - TypeError if a sub class or an instance is created.
    """

    def __call__(self, *args, **kwargs):
        raise TypeError("no public constructor available")

    def _create(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)
