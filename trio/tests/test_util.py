import signal
import warnings
import pytest

import trio
from .. import _core
from .._util import (
    signal_raise, ConflictDetector, is_main_thread, coroutine_or_error,
    generic_function, Final, NoPublicConstructor,
    SubclassingDeprecatedIn_v0_15_0
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
    assert trio.Cancelled.__module__ == "trio"
    assert trio.open_nursery.__module__ == "trio"
    assert trio.abc.Stream.__module__ == "trio.abc"
    assert trio.lowlevel.wait_task_rescheduled.__module__ == "trio.lowlevel"
    import trio.testing
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


async def test_coroutine_or_error():

    # error for: nursery.start_soon(trio.sleep(1))
    warnings.filterwarnings("error")

    async def test_afunc():
        pass

    with pytest.raises(TypeError):
        try:
            coroutine_or_error(test_afunc(), [])
        except RuntimeWarning:
            pass

    # error for: nursery.start_soon(future)

    # legacy @asyncio.coroutine functions
    def test_generator():
        yield None

    with pytest.raises(TypeError):
        coroutine_or_error(test_generator, [])

    # asyncio Future-like object
    class AsycioFutureLike:
        def __init__(self):
            self._asyncio_future_blocking = "im a value!"

    with pytest.raises(TypeError):
        coroutine_or_error(AsycioFutureLike(), [])

    # tornado Futures
    class Future:
        pass

    with pytest.raises(TypeError):
        coroutine_or_error(Future(), [])

    # twisted Deferreds
    class Deferreds:
        pass

    with pytest.raises(TypeError):
        coroutine_or_error(Deferreds(), [])

    # async generator
    async def test_agenerator():
        yield None

    with pytest.raises(TypeError):
        coroutine_or_error(test_agenerator, [])

    # synchronous function
    def test_fn():
        pass

    with pytest.raises(TypeError):
        coroutine_or_error(test_fn, [])


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


def test_subclassing_deprecated_metaclass():
    class Blah(metaclass=SubclassingDeprecatedIn_v0_15_0):
        pass

    with pytest.warns(trio.TrioDeprecationWarning):

        class Blah2(Blah):
            pass


def test_no_public_constructor_metaclass():
    class SpecialClass(metaclass=NoPublicConstructor):
        pass

    with pytest.raises(TypeError):
        SpecialClass()

    with pytest.raises(TypeError):

        class SubClass(SpecialClass):
            pass

    # Private constructor should not raise
    assert isinstance(SpecialClass._create(), SpecialClass)
