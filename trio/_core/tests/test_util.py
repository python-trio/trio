import pytest

def check_exc_chain(exc, chain, complete=True):
    while chain:
        assert type(exc) is chain.pop(0)
        if chain:
            exc = getattr(exc, "__{}__".format(chain.pop(0)))
    if complete:
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
