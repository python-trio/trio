import sys
import pytest
from async_generator import async_generator, yield_

from ... import _core
from .test_util import check_exc_chain
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

def test_Result_combine():
    # Trivial cases
    assert Result.combine(None, None) is None
    assert Result.combine(None, Value(1)) == Value(1)
    assert Result.combine(Value(1), None) == Value(1)
    with pytest.raises(TypeError):
        Result.combine("hello", None)
    with pytest.raises(TypeError):
        Result.combine(None, "hello")
    with pytest.raises(TypeError):
        Result.combine("hello", Error(RuntimeError()))
    with pytest.raises(TypeError):
        Result.combine(Value("hello"), "hello")

    # Value cases
    e = Error(RuntimeError())
    v = Value(1)
    with pytest.raises(ValueError):
        Result.combine(v, v)
    assert Result.combine(v, e) is e
    assert Result.combine(e, v) is e

    # Error+Error cases: check simple chaining
    e1 = Error(RuntimeError())
    e2 = Result.combine(e1, Error(ValueError()))
    check_exc_chain(e2.error, [ValueError, "context", RuntimeError])
    assert e2.error.__context__ is e1.error

def test_Result_combine_graft():
    # Grafting chains together
    def value_cause_runtime():
        try:
            try:
                raise RuntimeError
            except RuntimeError as exc:
                raise ValueError from exc
        except Exception as exc:
            return Error(exc)
    check_exc_chain(value_cause_runtime().error, [
        ValueError, "cause", RuntimeError])

    def name_context_key():
        try:
            try:
                raise KeyError
            except KeyError as exc:
                raise NameError
        except Exception as exc:
            return Error(exc)
    check_exc_chain(name_context_key().error, [
        NameError, "context", KeyError])

    def syntax_from_None():
        try:
            try:
                raise AssertionError
            except AssertionError as exc:
                raise SyntaxError from None
        except Exception as exc:
            return Error(exc)
    # the AssertionError is still there as __context__
    check_exc_chain(syntax_from_None().error, [
        SyntaxError, "context", AssertionError])
    assert syntax_from_None().error.__cause__ is None
    assert syntax_from_None().error.__suppress_context__

    c1 = Result.combine(value_cause_runtime(), name_context_key())
    check_exc_chain(c1.error, [
        NameError, "context", KeyError,
        "context", ValueError, "cause", RuntimeError])

    c2 = Result.combine(name_context_key(), value_cause_runtime())
    check_exc_chain(c2.error, [
        ValueError, "cause", RuntimeError,
        "context", NameError, "context", KeyError])

    c3 = Result.combine(syntax_from_None(), value_cause_runtime())
    check_exc_chain(c3.error, [
        ValueError, "cause", RuntimeError,
        "context", SyntaxError, "context", AssertionError])

    c4 = Result.combine(value_cause_runtime(), syntax_from_None())
    check_exc_chain(c4.error, [
        SyntaxError,
        "context", ValueError, "cause", RuntimeError])
