import pytest

from ..._core._result import *

def test_Result():
    v = Value(1)
    assert v.value == 1
    assert v.unwrap() == 1
    assert not hasattr(v, "__dict__")

    exc = RuntimeError("oops")
    e = Error(exc)
    assert e.error is exc
    with pytest.raises(RuntimeError):
        e.unwrap()
    assert not hasattr(e, "__dict__")

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

def test_Result_combine():
    r = None
    r = Result.combine(r, Error(RuntimeError()))
    assert type(r) is Error
    assert type(r.error) is RuntimeError
    r = Result.combine(r, Error(ValueError()))
    assert type(r.error) is ValueError
    assert type(r.error.__context__) is RuntimeError
