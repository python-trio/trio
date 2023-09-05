import signal
import sys
import types

import pytest

import trio

from .. import _core
from .._core._tests.tutil import (
    create_asyncio_future_in_new_loop,
    ignore_coroutine_never_awaited_warnings,
)
from .._util import (
    ConflictDetector,
    Final,
    NoPublicConstructor,
    coroutine_or_error,
    final,
    fixup_module_metadata,
    generic_function,
    is_main_thread,
    signal_raise,
)
from ..testing import wait_all_tasks_blocked


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
    import trio.testing

    assert trio.Cancelled.__module__ == "trio"
    assert trio.open_nursery.__module__ == "trio"
    assert trio.abc.Stream.__module__ == "trio.abc"
    assert trio.lowlevel.wait_task_rescheduled.__module__ == "trio.lowlevel"
    assert trio.testing.trio_test.__module__ == "trio.testing"

    # Also check methods
    assert trio.lowlevel.ParkingLot.__init__.__module__ == "trio.lowlevel"
    assert trio.abc.Stream.send_all.__module__ == "trio.abc"

    # And names
    assert trio.Cancelled.__name__ == "Cancelled"
    assert trio.Cancelled.__qualname__ == "Cancelled"
    assert trio.abc.SendStream.send_all.__name__ == "send_all"
    assert trio.abc.SendStream.send_all.__qualname__ == "SendStream.send_all"
    assert trio.to_thread.__name__ == "trio.to_thread"
    assert trio.to_thread.run_sync.__name__ == "run_sync"
    assert trio.to_thread.run_sync.__qualname__ == "run_sync"


async def test_is_main_thread():
    assert is_main_thread()

    def not_main_thread():
        assert not is_main_thread()

    await trio.to_thread.run_sync(not_main_thread)


# @coroutine is deprecated since python 3.8, which is fine with us.
@pytest.mark.filterwarnings("ignore:.*@coroutine.*:DeprecationWarning")
def test_coroutine_or_error():
    class Deferred:
        "Just kidding"

    with ignore_coroutine_never_awaited_warnings():

        async def f():  # pragma: no cover
            pass

        with pytest.raises(TypeError) as excinfo:
            coroutine_or_error(f())
        assert "expecting an async function" in str(excinfo.value)

        import asyncio

        if sys.version_info < (3, 11):

            @asyncio.coroutine
            def generator_based_coro():  # pragma: no cover
                yield from asyncio.sleep(1)

            with pytest.raises(TypeError) as excinfo:
                coroutine_or_error(generator_based_coro())
            assert "asyncio" in str(excinfo.value)

        with pytest.raises(TypeError) as excinfo:
            coroutine_or_error(create_asyncio_future_in_new_loop())
        assert "asyncio" in str(excinfo.value)

        with pytest.raises(TypeError) as excinfo:
            coroutine_or_error(create_asyncio_future_in_new_loop)
        assert "asyncio" in str(excinfo.value)

        with pytest.raises(TypeError) as excinfo:
            coroutine_or_error(Deferred())
        assert "twisted" in str(excinfo.value)

        with pytest.raises(TypeError) as excinfo:
            coroutine_or_error(lambda: Deferred())
        assert "twisted" in str(excinfo.value)

        with pytest.raises(TypeError) as excinfo:
            coroutine_or_error(len, [[1, 2, 3]])

        assert "appears to be synchronous" in str(excinfo.value)

        async def async_gen(arg):  # pragma: no cover
            yield

        with pytest.raises(TypeError) as excinfo:
            coroutine_or_error(async_gen, [0])
        msg = "expected an async function but got an async generator"
        assert msg in str(excinfo.value)

        # Make sure no references are kept around to keep anything alive
        del excinfo


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

    with pytest.raises(TypeError):

        class SubClass(FinalClass):
            pass


def test_final_deco() -> None:
    @final
    class FinalClass:
        pass

    with pytest.raises(TypeError):

        class SubClass(FinalClass):  # type: ignore[misc]
            pass


def test_no_public_constructor_metaclass():
    class SpecialClass(metaclass=NoPublicConstructor):
        pass

    with pytest.raises(TypeError):
        SpecialClass()

    # Private constructor should not raise
    assert isinstance(SpecialClass._create(), SpecialClass)


def test_fixup_module_metadata():
    # Ignores modules not in the trio.X tree.
    non_trio_module = types.ModuleType("not_trio")
    non_trio_module.some_func = lambda: None
    non_trio_module.some_func.__name__ = "some_func"
    non_trio_module.some_func.__qualname__ = "some_func"

    fixup_module_metadata(non_trio_module.__name__, vars(non_trio_module))

    assert non_trio_module.some_func.__name__ == "some_func"
    assert non_trio_module.some_func.__qualname__ == "some_func"

    # Bulild up a fake module to test. Just use lambdas since all we care about is the names.
    mod = types.ModuleType("trio._somemodule_impl")
    mod.some_func = lambda: None
    mod.some_func.__name__ = "_something_else"
    mod.some_func.__qualname__ = "_something_else"

    # No __module__ means it's unchanged.
    mod.not_funclike = types.SimpleNamespace()
    mod.not_funclike.__name__ = "not_funclike"

    # Check __qualname__ being absent works.
    mod.only_has_name = types.SimpleNamespace()
    mod.only_has_name.__module__ = "trio._somemodule_impl"
    mod.only_has_name.__name__ = "only_name"

    # Underscored names are unchanged.
    mod._private = lambda: None
    mod._private.__module__ = "trio._somemodule_impl"
    mod._private.__name__ = mod._private.__qualname__ = "_private"

    # We recurse into classes.
    mod.SomeClass = type(
        "SomeClass",
        (),
        {
            "__init__": lambda self: None,
            "method": lambda self: None,
        },
    )
    mod.SomeClass.recursion = mod.SomeClass  # Reference loop is fine.

    fixup_module_metadata("trio.somemodule", vars(mod))
    assert mod.some_func.__name__ == "some_func"
    assert mod.some_func.__module__ == "trio.somemodule"
    assert mod.some_func.__qualname__ == "some_func"

    assert mod.not_funclike.__name__ == "not_funclike"
    assert mod._private.__name__ == "_private"
    assert mod._private.__module__ == "trio._somemodule_impl"
    assert mod._private.__qualname__ == "_private"

    assert mod.only_has_name.__name__ == "only_has_name"
    assert mod.only_has_name.__module__ == "trio.somemodule"
    assert not hasattr(mod.only_has_name, "__qualname__")

    assert mod.SomeClass.method.__name__ == "method"
    assert mod.SomeClass.method.__module__ == "trio.somemodule"
    assert mod.SomeClass.method.__qualname__ == "SomeClass.method"
    # Make coverage happy.
    non_trio_module.some_func()
    mod.some_func()
    mod._private()
    mod.SomeClass().method()
