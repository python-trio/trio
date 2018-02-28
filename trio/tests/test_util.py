import os
import pathlib
import signal
import sys

import pytest
import threading
from async_generator import async_generator, yield_

from .. import _core
from .._threads import run_sync_in_worker_thread
from .._util import (acontextmanager, signal_raise, ConflictDetector, fspath,
                     is_main_thread)
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

    async with ul1:
        with assert_checkpoints():
            async with ul2:
                print("ok")

    with pytest.raises(_core.ResourceBusyError) as excinfo:
        async with ul1:
            with assert_checkpoints():
                async with ul1:
                    pass  # pragma: no cover
    assert "ul1" in str(excinfo.value)

    async def wait_with_ul1():
        async with ul1:
            await wait_all_tasks_blocked()

    with pytest.raises(_core.ResourceBusyError) as excinfo:
        async with _core.open_nursery() as nursery:
            nursery.start_soon(wait_with_ul1)
            nursery.start_soon(wait_with_ul1)
    assert "ul1" in str(excinfo.value)

    # mixing sync and async entry
    with pytest.raises(_core.ResourceBusyError) as excinfo:
        with ul1.sync:
            with assert_checkpoints():
                async with ul1:
                    pass  # pragma: no cover
    assert "ul1" in str(excinfo.value)


async def test_contextmanager_do_not_unchain_non_stopiteration_exceptions():
    @acontextmanager
    @async_generator
    async def manager_issue29692():
        try:
            await yield_()
        except Exception as exc:
            raise RuntimeError('issue29692:Chained') from exc

    with pytest.raises(RuntimeError) as excinfo:
        async with manager_issue29692():
            raise ZeroDivisionError
    assert excinfo.value.args[0] == 'issue29692:Chained'
    assert isinstance(excinfo.value.__cause__, ZeroDivisionError)

    # This is a little funky because of implementation details in
    # async_generator It can all go away once we stop supporting Python3.5
    with pytest.raises(RuntimeError) as excinfo:
        async with manager_issue29692():
            exc = StopIteration('issue29692:Unchained')
            raise exc
    assert excinfo.value.args[0] == 'issue29692:Chained'
    cause = excinfo.value.__cause__
    assert cause.args[0] == 'generator raised StopIteration'
    assert cause.__cause__ is exc

    with pytest.raises(StopAsyncIteration) as excinfo:
        async with manager_issue29692():
            raise StopAsyncIteration('issue29692:Unchained')
    assert excinfo.value.args[0] == 'issue29692:Unchained'
    assert excinfo.value.__cause__ is None

    @acontextmanager
    @async_generator
    async def noop_async_context_manager():
        await yield_()

    with pytest.raises(StopIteration):
        async with noop_async_context_manager():
            raise StopIteration


# Native async generators are only available from Python 3.6 and onwards
nativeasyncgenerators = True
try:
    exec(
        """
@acontextmanager
async def manager_issue29692_2():
    try:
        yield
    except Exception as exc:
        raise RuntimeError('issue29692:Chained') from exc
"""
    )
except SyntaxError:
    nativeasyncgenerators = False


@pytest.mark.skipif(
    not nativeasyncgenerators,
    reason="Python < 3.6 doesn't have native async generators"
)
async def test_native_contextmanager_do_not_unchain_non_stopiteration_exceptions(
):

    with pytest.raises(RuntimeError) as excinfo:
        async with manager_issue29692_2():
            raise ZeroDivisionError
    assert excinfo.value.args[0] == 'issue29692:Chained'
    assert isinstance(excinfo.value.__cause__, ZeroDivisionError)

    for cls in [StopIteration, StopAsyncIteration]:
        with pytest.raises(cls) as excinfo:
            async with manager_issue29692_2():
                raise cls('issue29692:Unchained')
        assert excinfo.value.args[0] == 'issue29692:Unchained'
        assert excinfo.value.__cause__ is None


async def test_acontextmanager_exception_passthrough():
    # This was the cause of annoying coverage flapping, see gh-140
    @acontextmanager
    @async_generator
    async def noop_async_context_manager():
        await yield_()

    for exc_type in [StopAsyncIteration, RuntimeError, ValueError]:
        with pytest.raises(exc_type):
            async with noop_async_context_manager():
                raise exc_type


async def test_acontextmanager_catches_exception():
    @acontextmanager
    @async_generator
    async def catch_it():
        with pytest.raises(ValueError):
            await yield_()

    async with catch_it():
        raise ValueError


async def test_acontextmanager_no_yield():
    @acontextmanager
    @async_generator
    async def yeehaw():
        pass

    with pytest.raises(RuntimeError) as excinfo:
        async with yeehaw():
            assert False  # pragma: no cover

    assert "didn't yield" in str(excinfo.value)


async def test_acontextmanager_too_many_yields():
    @acontextmanager
    @async_generator
    async def doubleyield():
        try:
            await yield_()
        except Exception:
            pass
        await yield_()

    with pytest.raises(RuntimeError) as excinfo:
        async with doubleyield():
            pass

    assert "didn't stop" in str(excinfo.value)

    with pytest.raises(RuntimeError) as excinfo:
        async with doubleyield():
            raise ValueError

    assert "didn't stop after athrow" in str(excinfo.value)


async def test_acontextmanager_requires_asyncgenfunction():
    with pytest.raises(TypeError):

        @acontextmanager
        def syncgen():  # pragma: no cover
            yield


def test_module_metadata_is_fixed_up():
    import trio
    assert trio.Cancelled.__module__ == "trio"
    assert trio.open_cancel_scope.__module__ == "trio"
    assert trio.ssl.SSLStream.__module__ == "trio.ssl"
    assert trio.abc.Stream.__module__ == "trio.abc"
    assert trio.hazmat.wait_task_rescheduled.__module__ == "trio.hazmat"
    import trio.testing
    assert trio.testing.trio_test.__module__ == "trio.testing"

    # Also check methods
    assert trio.ssl.SSLStream.__init__.__module__ == "trio.ssl"
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


class TestFspath(object):

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

    await run_sync_in_worker_thread(not_main_thread)
