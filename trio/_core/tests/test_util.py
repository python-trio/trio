# This file is somewhat misnamed -- it has tests for ../_util.py, but also has
# utilities for testing.

import pytest

from ... import _core

def check_sequence_matches(seq, template):
    i = 0
    for pattern in template:
        if not isinstance(pattern, set):
            pattern = {pattern}
        got = set(seq[i:i + len(pattern)])
        assert got == pattern
        i += len(got)

def test_check_sequence_matches():
    check_sequence_matches([1, 2, 3], [1, 2, 3])
    with pytest.raises(AssertionError):
        check_sequence_matches([1, 3, 2], [1, 2, 3])
    check_sequence_matches([1, 2, 3, 4], [1, {2, 3}, 4])
    check_sequence_matches([1, 3, 2, 4], [1, {2, 3}, 4])
    with pytest.raises(AssertionError):
        check_sequence_matches([1, 2, 4, 3], [1, {2, 3}, 4])


def check_exc_chain(exc, chain, complete=True):
    while chain:
        assert type(exc) is chain.pop(0)
        if chain:
            exc = getattr(exc, "__{}__".format(chain.pop(0)))
    if complete:  # pragma: no branch
        assert exc.__cause__ is None
        assert exc.__context__ is None

# Example:
#   check_exc_chain(
#     exc, [UnhandledExceptionError, "cause", KeyError, "context", ...]

def test_check_exc_chain():
    exc = ValueError()
    exc.__context__ = KeyError()
    exc.__context__.__cause__ = RuntimeError()
    exc.__context__.__cause__.__cause__ = TypeError()

    check_exc_chain(exc, [
        ValueError, "context", KeyError, "cause", RuntimeError, "cause",
        TypeError,
    ])
    with pytest.raises(AssertionError):
        check_exc_chain(exc, [
            NameError, "context", KeyError, "cause", RuntimeError, "cause",
            TypeError,
        ])
    with pytest.raises(AssertionError):
        check_exc_chain(exc, [
            ValueError, "cause", KeyError, "cause", RuntimeError, "cause",
            TypeError,
        ])
    with pytest.raises(AssertionError):
        check_exc_chain(exc, [
            ValueError, "context", KeyError, "cause", RuntimeError, "cause",
            NameError,
        ])
