import sys
import pytest
from async_generator import async_generator, yield_

from ... import _core
from ..._core._result import *

def test_Result():
    v = Value(1)
    assert v.value == 1
    assert v.unwrap() == 1
    assert not hasattr(v, "__dict__")
    assert repr(v) == "Value(1)"

    exc = RuntimeError("oops")
    e = Error(exc)
    assert e.error is exc
    with pytest.raises(RuntimeError):
        e.unwrap()
    assert not hasattr(e, "__dict__")
    assert repr(e) == "Error(RuntimeError('oops',))"

    with pytest.raises(TypeError):
        Error("hello")
    with pytest.raises(TypeError):
        Error(RuntimeError)

    def expect_1():
        assert (yield) == 1
        yield "ok"

    it = iter(expect_1())
    next(it)
    assert v.send(it) == "ok"

    def expect_RuntimeError():
        with pytest.raises(RuntimeError):
            yield
        yield "ok"
    it = iter(expect_RuntimeError())
    next(it)
    assert e.send(it) == "ok"

def test_Result_eq_hash():
    v1 = Value(["hello"])
    v2 = Value(["hello"])
    v3 = Value("hello")
    v4 = Value("hello")
    assert v1 == v2
    assert v1 != v3
    with pytest.raises(TypeError):
        {v1}
    assert {v3, v4} == {v3}

    # exceptions in general compare by identity
    exc1 = RuntimeError("oops")
    exc2 = KeyError("foo")
    e1 = Error(exc1)
    e2 = Error(exc1)
    e3 = Error(exc2)
    e4 = Error(exc2)
    assert e1 == e2
    assert e3 == e4
    assert e1 != e3
    assert {e1, e2, e3, e4} == {e1, e3}

def test_Value_compare():
    assert Value(1) < Value(2)
    assert not Value(3) < Value(2)
    with pytest.raises(TypeError):
        Value(1) < Value("foo")

def test_Result_capture():
    def return_arg(x):
        return x
    v = Result.capture(return_arg, 2)
    assert type(v) == Value
    assert v.unwrap() == 2

    def raise_ValueError(x):
        raise ValueError(x)
    e = Result.capture(raise_ValueError, "two")
    assert type(e) == Error
    assert type(e.error) is ValueError
    assert e.error.args == ("two",)

async def test_Result_acapture():
    async def return_arg(x):
        await _core.yield_briefly()
        return x
    v = await Result.acapture(return_arg, 7)
    assert v == Value(7)

    async def raise_ValueError(x):
        await _core.yield_briefly()
        raise ValueError(x)
    e = await Result.acapture(raise_ValueError, 9)
    assert type(e.error) is ValueError
    assert e.error.args == (9,)

async def test_Result_asend():
    @async_generator
    async def my_agen_func():
        assert (await yield_(1)) == "value"
        with pytest.raises(KeyError):
            await yield_(2)
        await yield_(3)
    my_agen = my_agen_func().__aiter__()
    if sys.version_info < (3, 5, 2):
        my_agen = await my_agen
    assert (await my_agen.asend(None)) == 1
    assert (await Value("value").asend(my_agen)) == 2
    assert (await Error(KeyError()).asend(my_agen)) == 3
    with pytest.raises(StopAsyncIteration):
        await my_agen.asend(None)
