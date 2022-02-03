import gc
import logging
import pytest

from traceback import (
    extract_tb,
    print_exception,
    format_exception,
)
from traceback import _cause_message  # type: ignore
import sys
import re

from .._multierror import MultiError, concat_tb
from ..._core import open_nursery


class NotHashableException(Exception):
    code = None

    def __init__(self, code):
        super().__init__()
        self.code = code

    def __eq__(self, other):
        if not isinstance(other, NotHashableException):
            return False
        return self.code == other.code


async def raise_nothashable(code):
    raise NotHashableException(code)


def raiser1():
    raiser1_2()


def raiser1_2():
    raiser1_3()


def raiser1_3():
    raise ValueError("raiser1_string")


def raiser2():
    raiser2_2()


def raiser2_2():
    raise KeyError("raiser2_string")


def raiser3():
    raise NameError


def get_exc(raiser):
    try:
        raiser()
    except Exception as exc:
        return exc


def get_tb(raiser):
    return get_exc(raiser).__traceback__


def einfo(exc):
    return (type(exc), exc, exc.__traceback__)


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
    assert m.exceptions == (exc1, exc2)
    assert "ValueError" in str(m)
    assert "ValueError" in repr(m)

    with pytest.raises(TypeError):
        MultiError(object())
    with pytest.raises(TypeError):
        MultiError([KeyError(), ValueError])


def test_MultiErrorOfSingleMultiError():
    # For MultiError([MultiError]), ensure there is no bad recursion by the
    # constructor where __init__ is called if __new__ returns a bare MultiError.
    exceptions = (KeyError(), ValueError())
    a = MultiError(exceptions)
    b = MultiError([a])
    assert b == a
    assert b.exceptions == exceptions


async def test_MultiErrorNotHashable():
    exc1 = NotHashableException(42)
    exc2 = NotHashableException(4242)
    exc3 = ValueError()
    assert exc1 != exc2
    assert exc1 != exc3

    with pytest.raises(MultiError):
        async with open_nursery() as nursery:
            nursery.start_soon(raise_nothashable, 42)
            nursery.start_soon(raise_nothashable, 4242)


def test_MultiError_filter_NotHashable():
    excs = MultiError([NotHashableException(42), ValueError()])

    def handle_ValueError(exc):
        if isinstance(exc, ValueError):
            return None
        else:
            return exc

    filtered_excs = pytest.deprecated_call(MultiError.filter, handle_ValueError, excs)
    assert isinstance(filtered_excs, NotHashableException)


def test_traceback_recursion():
    exc1 = RuntimeError()
    exc2 = KeyError()
    exc3 = NotHashableException(42)
    # Note how this creates a loop, where exc1 refers to exc1
    # This could trigger an infinite recursion; the 'seen' set is supposed to prevent
    # this.
    exc1.__cause__ = MultiError([exc1, exc2, exc3])
    format_exception(*einfo(exc1))


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
    assert pytest.deprecated_call(MultiError.filter, null_handler, m) is m
    assert_tree_eq(m, make_tree())

    # Make sure we don't pick up any detritus if run in a context where
    # implicit exception chaining would like to kick in
    m = make_tree()
    try:
        raise ValueError
    except ValueError:
        assert pytest.deprecated_call(MultiError.filter, null_handler, m) is m
    assert_tree_eq(m, make_tree())

    def simple_filter(exc):
        if isinstance(exc, ValueError):
            return None
        if isinstance(exc, KeyError):
            return RuntimeError()
        return exc

    new_m = pytest.deprecated_call(MultiError.filter, simple_filter, make_tree())
    assert isinstance(new_m, MultiError)
    assert len(new_m.exceptions) == 2
    # was: [[ValueError, KeyError], NameError]
    # ValueError disappeared & KeyError became RuntimeError, so now:
    assert isinstance(new_m.exceptions[0], RuntimeError)
    assert isinstance(new_m.exceptions[1], NameError)

    # implicit chaining:
    assert isinstance(new_m.exceptions[0].__context__, KeyError)

    # also, the traceback on the KeyError incorporates what used to be the
    # traceback on its parent MultiError
    orig = make_tree()
    # make sure we have the right path
    assert isinstance(orig.exceptions[0].exceptions[1], KeyError)
    # get original traceback summary
    orig_extracted = (
        extract_tb(orig.__traceback__)
        + extract_tb(orig.exceptions[0].__traceback__)
        + extract_tb(orig.exceptions[0].exceptions[1].__traceback__)
    )

    def p(exc):
        print_exception(type(exc), exc, exc.__traceback__)

    p(orig)
    p(orig.exceptions[0])
    p(orig.exceptions[0].exceptions[1])
    p(new_m.exceptions[0].__context__)
    # compare to the new path
    assert new_m.__traceback__ is None
    new_extracted = extract_tb(new_m.exceptions[0].__context__.__traceback__)
    assert orig_extracted == new_extracted

    # check preserving partial tree
    def filter_NameError(exc):
        if isinstance(exc, NameError):
            return None
        return exc

    m = make_tree()
    new_m = pytest.deprecated_call(MultiError.filter, filter_NameError, m)
    # with the NameError gone, the other branch gets promoted
    assert new_m is m.exceptions[0]

    # check fully handling everything
    def filter_all(exc):
        return None

    assert pytest.deprecated_call(MultiError.filter, filter_all, make_tree()) is None


def test_MultiError_catch():
    # No exception to catch

    def noop(_):
        pass  # pragma: no cover

    with pytest.deprecated_call(MultiError.catch, noop):
        pass

    # Simple pass-through of all exceptions
    m = make_tree()
    with pytest.raises(MultiError) as excinfo:
        with pytest.deprecated_call(MultiError.catch, lambda exc: exc):
            raise m
    assert excinfo.value is m
    # Should be unchanged, except that we added a traceback frame by raising
    # it here
    assert m.__traceback__ is not None
    assert m.__traceback__.tb_frame.f_code.co_name == "test_MultiError_catch"
    assert m.__traceback__.tb_next is None
    m.__traceback__ = None
    assert_tree_eq(m, make_tree())

    # Swallows everything
    with pytest.deprecated_call(MultiError.catch, lambda _: None):
        raise make_tree()

    def simple_filter(exc):
        if isinstance(exc, ValueError):
            return None
        if isinstance(exc, KeyError):
            return RuntimeError()
        return exc

    with pytest.raises(MultiError) as excinfo:
        with pytest.deprecated_call(MultiError.catch, simple_filter):
            raise make_tree()
    new_m = excinfo.value
    assert isinstance(new_m, MultiError)
    assert len(new_m.exceptions) == 2
    # was: [[ValueError, KeyError], NameError]
    # ValueError disappeared & KeyError became RuntimeError, so now:
    assert isinstance(new_m.exceptions[0], RuntimeError)
    assert isinstance(new_m.exceptions[1], NameError)
    # Make sure that Python did not successfully attach the old MultiError to
    # our new MultiError's __context__
    assert not new_m.__suppress_context__
    assert new_m.__context__ is None

    # check preservation of __cause__ and __context__
    v = ValueError()
    v.__cause__ = KeyError()
    with pytest.raises(ValueError) as excinfo:
        with pytest.deprecated_call(MultiError.catch, lambda exc: exc):
            raise v
    assert isinstance(excinfo.value.__cause__, KeyError)

    v = ValueError()
    context = KeyError()
    v.__context__ = context
    with pytest.raises(ValueError) as excinfo:
        with pytest.deprecated_call(MultiError.catch, lambda exc: exc):
            raise v
    assert excinfo.value.__context__ is context
    assert not excinfo.value.__suppress_context__

    for suppress_context in [True, False]:
        v = ValueError()
        context = KeyError()
        v.__context__ = context
        v.__suppress_context__ = suppress_context
        distractor = RuntimeError()
        with pytest.raises(ValueError) as excinfo:

            def catch_RuntimeError(exc):
                if isinstance(exc, RuntimeError):
                    return None
                else:
                    return exc

            with pytest.deprecated_call(MultiError.catch, catch_RuntimeError):
                raise MultiError([v, distractor])
        assert excinfo.value.__context__ is context
        assert excinfo.value.__suppress_context__ == suppress_context


@pytest.mark.skipif(
    sys.implementation.name != "cpython", reason="Only makes sense with refcounting GC"
)
def test_MultiError_catch_doesnt_create_cyclic_garbage():
    # https://github.com/python-trio/trio/pull/2063
    gc.collect()
    old_flags = gc.get_debug()

    def make_multi():
        # make_tree creates cycles itself, so a simple
        raise MultiError([get_exc(raiser1), get_exc(raiser2)])

    def simple_filter(exc):
        if isinstance(exc, ValueError):
            return Exception()
        if isinstance(exc, KeyError):
            return RuntimeError()
        assert False, "only ValueError and KeyError should exist"  # pragma: no cover

    try:
        gc.set_debug(gc.DEBUG_SAVEALL)
        with pytest.raises(MultiError):
            # covers MultiErrorCatcher.__exit__ and _multierror.copy_tb
            with pytest.deprecated_call(MultiError.catch, simple_filter):
                raise make_multi()
        gc.collect()
        assert not gc.garbage
    finally:
        gc.set_debug(old_flags)
        gc.garbage.clear()


def assert_match_in_seq(pattern_list, string):
    offset = 0
    print("looking for pattern matches...")
    for pattern in pattern_list:
        print("checking pattern:", pattern)
        reobj = re.compile(pattern)
        match = reobj.search(string, offset)
        assert match is not None
        offset = match.end()


def test_assert_match_in_seq():
    assert_match_in_seq(["a", "b"], "xx a xx b xx")
    assert_match_in_seq(["b", "a"], "xx b xx a xx")
    with pytest.raises(AssertionError):
        assert_match_in_seq(["a", "b"], "xx b xx a xx")
