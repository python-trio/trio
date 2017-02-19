import pytest

from traceback import extract_tb

from ..._util import run_sync_coro

from .._multierror import (
    MultiError, format_exception_multi, concat_tb,
)

def raiser1():
    raiser1_2()

def raiser1_2():
    raiser1_3()

def raiser1_3():
    raise ValueError

def raiser2():
    raiser2_2()

def raiser2_2():
    raise KeyError

def raiser3():
    raise NameError

def get_exc(raiser):
    try:
        raiser()
    except Exception as exc:
        return exc

def get_tb(raiser):
    return get_exc(raiser).__traceback__

def test_concat_tb():

    tb1 = get_tb(raiser1)
    tb2 = get_tb(raiser2)

    # These return a list of (filename, lineno, fn name, text) tuples
    # https://docs.python.org/3/library/traceback.html#traceback.extract_tb
    entries1 = extract_tb(tb1)
    entries2 = extract_tb(tb2)

    tb12 = concat_tb(tb1, tb2)
    assert extract_tb(tb12) == entries1 + entries2

    tb21 = concat_tb(tb2, tb1)
    assert extract_tb(tb21) == entries2 + entries1

    # Check degenerate cases
    assert extract_tb(concat_tb(None, tb1)) == entries1
    assert extract_tb(concat_tb(tb1, None)) == entries1
    assert concat_tb(None, None) is None

    # Make sure the original tracebacks didn't get mutated by mistake
    assert extract_tb(get_tb(raiser1)) == entries1
    assert extract_tb(get_tb(raiser2)) == entries2

def test_MultiError():
    exc1 = get_exc(raiser1)
    exc2 = get_exc(raiser2)

    assert MultiError([exc1]) is exc1
    m = MultiError([exc1, exc2])
    assert m.exceptions == [exc1, exc2]
    assert "ValueError" in str(m)
    assert "ValueError" in repr(m)

def make_tree():
    # Returns an object like:
    #   MultiError([
    #     MultiError([
    #       ValueError,
    #       KeyError,
    #     ]),
    #     NameError,
    #   ])
    # where all exceptions except the root have a non-trivial traceback.
    exc1 = get_exc(raiser1)
    exc2 = get_exc(raiser2)
    exc3 = get_exc(raiser3)

    # Give m12 a non-trivial traceback
    try:
        raise MultiError([exc1, exc2])
    except BaseException as m12:
        return MultiError([m12, exc3])

def assert_tree_eq(m1, m2):
    if m1 is None or m2 is None:
        assert m1 is m2
        return
    assert type(m1) is type(m2)
    assert extract_tb(m1.__traceback__) == extract_tb(m2.__traceback__)
    assert_tree_eq(m1.__cause__, m2.__cause__)
    assert_tree_eq(m1.__context__, m2.__context__)
    if isinstance(m1, MultiError):
        assert len(m1.exceptions) == len(m2.exceptions)
        for e1, e2 in zip(m1.exceptions, m2.exceptions):
            assert_tree_eq(e1, e2)

def test_MultiError_filter():
    def null_handler(exc):
        return exc

    m = make_tree()
    assert_tree_eq(m, m)
    assert MultiError.filter(null_handler, m) is m
    assert_tree_eq(m, make_tree())

    async def null_ahandler(exc):
        return exc

    m = make_tree()
    assert run_sync_coro(MultiError.afilter, null_ahandler, m) is m
    assert_tree_eq(m, make_tree())
