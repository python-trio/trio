import os
import pathlib
import signal
import sys

import pytest

import trio
from .. import _core
from .._util import (
    signal_raise, ConflictDetector, fspath, is_main_thread, generic_function,
    Final, NoPublicConstructor
)
from ..testing import wait_all_tasks_blocked, assert_checkpoints


def raise_(exc):
    """ Raise provided exception.
    Just a helper for raising exceptions from lambdas. """
    raise exc


def test_signal_raise():
    record = []

    def handler(signum, _):
        record.append(signum)

    old = signal.signal(signal.SIGFPE, handler)
    try:
        signal_raise(signal.SIGFPE)
    finally:
        signal.signal(signal.SIGFPE, old)
    assert record == [signal.SIGFPE]


async def test_ConflictDetector():
    ul1 = ConflictDetector("ul1")
    ul2 = ConflictDetector("ul2")

    with ul1:
        with ul2:
            print("ok")

    with pytest.raises(_core.BusyResourceError) as excinfo:
        with ul1:
            with ul1:
                pass  # pragma: no cover
    assert "ul1" in str(excinfo.value)

    async def wait_with_ul1():
        with ul1:
            await wait_all_tasks_blocked()

    with pytest.raises(_core.BusyResourceError) as excinfo:
        async with _core.open_nursery() as nursery:
            nursery.start_soon(wait_with_ul1)
            nursery.start_soon(wait_with_ul1)
    assert "ul1" in str(excinfo.value)


def test_module_metadata_is_fixed_up():
    import trio
    assert trio.Cancelled.__module__ == "trio"
    assert trio.open_nursery.__module__ == "trio"
    assert trio.abc.Stream.__module__ == "trio.abc"
    assert trio.hazmat.wait_task_rescheduled.__module__ == "trio.hazmat"
    import trio.testing
    assert trio.testing.trio_test.__module__ == "trio.testing"

    # Also check methods
    assert trio.hazmat.ParkingLot.__init__.__module__ == "trio.hazmat"
    assert trio.abc.Stream.send_all.__module__ == "trio.abc"


# define a concrete class implementing the PathLike protocol
# Since we want to have compatibility with Python 3.5 we need
# to define the base class on runtime.
BaseKlass = os.PathLike if hasattr(os, "PathLike") else object


class ConcretePathLike(BaseKlass):
    """ Class implementing the file system path protocol."""

    def __init__(self, path=""):
        self.path = path

    def __fspath__(self):
        return self.path


class TestFspath:

    # based on:
    # https://github.com/python/cpython/blob/da6c3da6c33c6bf794f741e348b9c6d86cc43ec5/Lib/test/test_os.py#L3527-L3571

    @pytest.mark.parametrize(
        "path", (b'hello', b'goodbye', b'some/path/and/file')
    )
    def test_return_bytes(self, path):
        assert path == fspath(path)

    @pytest.mark.parametrize(
        "path", ('hello', 'goodbye', 'some/path/and/file')
    )
    def test_return_string(self, path):
        assert path == fspath(path)

    @pytest.mark.parametrize(
        "path", (pathlib.Path("/home"), pathlib.Path("C:\\windows"))
    )
    def test_handle_pathlib(self, path):
        assert str(path) == fspath(path)

    @pytest.mark.parametrize("path", ("path/like/object", b"path/like/object"))
    def test_handle_pathlike_protocol(self, path):
        pathlike = ConcretePathLike(path)
        assert path == fspath(pathlike)
        if sys.version_info > (3, 6):
            assert issubclass(ConcretePathLike, os.PathLike)
            assert isinstance(pathlike, os.PathLike)

    def test_argument_required(self):
        with pytest.raises(TypeError):
            fspath()

    def test_throw_error_at_multiple_arguments(self):
        with pytest.raises(TypeError):
            fspath(1, 2)

    @pytest.mark.parametrize(
        "klass", (23, object(), int, type, os, type("blah", (), {})())
    )
    def test_throw_error_at_non_pathlike(self, klass):
        with pytest.raises(TypeError):
            fspath(klass)

    @pytest.mark.parametrize(
        "exception, method",
        [
            (TypeError, 1),  # __fspath__ is not callable
            (TypeError, lambda x: 23
             ),  # __fspath__ returns a value other than str or bytes
            (Exception, lambda x: raise_(Exception)
             ),  # __fspath__raises a random exception
            (AttributeError, lambda x: raise_(AttributeError)
             ),  # __fspath__ raises AttributeError
        ]
    )
    def test_bad_pathlike_implementation(self, exception, method):
        klass = type('foo', (), {})
        klass.__fspath__ = method
        with pytest.raises(exception):
            fspath(klass())


async def test_is_main_thread():
    assert is_main_thread()

    def not_main_thread():
        assert not is_main_thread()

    await trio.to_thread.run_sync(not_main_thread)


def test_generic_function():
    @generic_function
    def test_func(arg):
        """Look, a docstring!"""
        return arg

    assert test_func is test_func[int] is test_func[int, str]
    assert test_func(42) == test_func[int](42) == 42
    assert test_func.__doc__ == "Look, a docstring!"
    assert test_func.__qualname__ == "test_generic_function.<locals>.test_func"
    assert test_func.__name__ == "test_func"
    assert test_func.__module__ == __name__


def test_final_metaclass():
    class FinalClass(metaclass=Final):
        pass

    with pytest.raises(
        TypeError, match="`FinalClass` does not support subclassing"
    ):

        class SubClass(FinalClass):
            pass


def test_no_public_constructor_metaclass():
    class SpecialClass(metaclass=NoPublicConstructor):
        pass

    with pytest.raises(TypeError, match="no public constructor available"):
        SpecialClass()

    with pytest.raises(
        TypeError, match="`SpecialClass` does not support subclassing"
    ):

        class SubClass(SpecialClass):
            pass

    # Private constructor should not raise
    assert isinstance(SpecialClass._create(), SpecialClass)
