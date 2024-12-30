from __future__ import annotations

import re
import sys
from types import TracebackType
from typing import TYPE_CHECKING

import pytest

import trio
from trio.testing import Matcher, RaisesGroup

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

if TYPE_CHECKING:
    from _pytest.python_api import RaisesContext


def wrap_escape(s: str) -> str:
    return "^" + re.escape(s) + "$"


def fails_raises_group(
    msg: str, add_prefix: bool = True
) -> RaisesContext[AssertionError]:
    prefix = "Raised exception group did not match: " if add_prefix else ""
    return pytest.raises(AssertionError, match=wrap_escape(prefix + msg))


def test_raises_group() -> None:
    with pytest.raises(
        ValueError,
        match=wrap_escape(
            f'Invalid argument "{TypeError()!r}" must be exception type, Matcher, or RaisesGroup.',
        ),
    ):
        RaisesGroup(TypeError())  # type: ignore[call-overload]
    with RaisesGroup(ValueError):
        raise ExceptionGroup("foo", (ValueError(),))

    with fails_raises_group("SyntaxError() is not of type 'ValueError'"):
        with RaisesGroup(ValueError):
            raise ExceptionGroup("foo", (SyntaxError(),))

    # multiple exceptions
    with RaisesGroup(ValueError, SyntaxError):
        raise ExceptionGroup("foo", (ValueError(), SyntaxError()))

    # order doesn't matter
    with RaisesGroup(SyntaxError, ValueError):
        raise ExceptionGroup("foo", (ValueError(), SyntaxError()))

    # nested exceptions
    with RaisesGroup(RaisesGroup(ValueError)):
        raise ExceptionGroup("foo", (ExceptionGroup("bar", (ValueError(),)),))

    with RaisesGroup(
        SyntaxError,
        RaisesGroup(ValueError),
        RaisesGroup(RuntimeError),
    ):
        raise ExceptionGroup(
            "foo",
            (
                SyntaxError(),
                ExceptionGroup("bar", (ValueError(),)),
                ExceptionGroup("", (RuntimeError(),)),
            ),
        )


def test_incorrect_number_exceptions() -> None:
    # We previously gave an error saying the number of exceptions was wrong,
    # but we now instead indicate excess/missing exceptions
    with fails_raises_group(
        "1 matched exception. Unexpected exception(s): [ValueError()]"
    ):
        with RaisesGroup(ValueError):
            raise ExceptionGroup("", (ValueError(), ValueError()))

    with fails_raises_group(
        "1 matched exception. Unexpected exception(s): [RuntimeError()]"
    ):
        with RaisesGroup(ValueError):
            raise ExceptionGroup("", (RuntimeError(), ValueError()))

    # will error if there's missing exceptions
    with fails_raises_group(
        "1 matched exception. Too few exceptions raised, found no match for: [<class 'SyntaxError'>]"
    ):
        with RaisesGroup(ValueError, SyntaxError):
            raise ExceptionGroup("", (ValueError(),))

    # TODO: this one should maybe say that it matched an already matched exception
    with fails_raises_group(
        "1 matched exception. Too few exceptions raised, found no match for: [<class 'ValueError'>]"
    ):
        with RaisesGroup(ValueError, ValueError):
            raise ExceptionGroup("", (ValueError(),))


def test_flatten_subgroups() -> None:
    # loose semantics, as with expect*
    with RaisesGroup(ValueError, flatten_subgroups=True):
        raise ExceptionGroup("", (ExceptionGroup("", (ValueError(),)),))

    with RaisesGroup(ValueError, TypeError, flatten_subgroups=True):
        raise ExceptionGroup("", (ExceptionGroup("", (ValueError(), TypeError())),))
    with RaisesGroup(ValueError, TypeError, flatten_subgroups=True):
        raise ExceptionGroup("", [ExceptionGroup("", [ValueError()]), TypeError()])

    # mixed loose is possible if you want it to be at least N deep
    with RaisesGroup(RaisesGroup(ValueError, flatten_subgroups=True)):
        raise ExceptionGroup("", (ExceptionGroup("", (ValueError(),)),))
    with RaisesGroup(RaisesGroup(ValueError, flatten_subgroups=True)):
        raise ExceptionGroup(
            "",
            (ExceptionGroup("", (ExceptionGroup("", (ValueError(),)),)),),
        )

    # but not the other way around
    with pytest.raises(
        ValueError,
        match="^You cannot specify a nested structure inside a RaisesGroup with",
    ):
        RaisesGroup(RaisesGroup(ValueError), flatten_subgroups=True)  # type: ignore[call-overload]

    # flatten_subgroups is not sufficient to catch fully unwrapped
    with fails_raises_group(
        "ValueError() is not an exception group, but would match with `allow_unwrapped=True`"
    ):
        with RaisesGroup(ValueError, flatten_subgroups=True):
            raise ValueError
    with fails_raises_group(
        "RaisesGroup(ValueError, flatten_subgroups=True): ValueError() is not an exception group, but would match with `allow_unwrapped=True`"
    ):
        with RaisesGroup(RaisesGroup(ValueError, flatten_subgroups=True)):
            raise ExceptionGroup("", (ValueError(),))

    # helpful suggestion if flatten_subgroups would make it pass
    # TODO: this one is overly verbose - in the case of a single [unmatched] raised exception we don't need a table.
    # TODO: Printing Exceptiongroup('', [ValueError(), TypeError()]) three times is also a different issue
    with fails_raises_group(
        "Raised exception group did not match: \n"
        "The following expected exceptions did not find a match: [<class 'ValueError'>, <class 'TypeError'>]\n"
        "The following raised exceptions did not find a match\n"
        "  ExceptionGroup('', [ValueError(), TypeError()]):\n"
        "    ExceptionGroup('', [ValueError(), TypeError()]) is not of type 'ValueError'\n"
        "    ExceptionGroup('', [ValueError(), TypeError()]) is not of type 'TypeError'\n"
        "Did you mean to use `flatten_subgroups=True`?",
        add_prefix=False,
    ):
        with RaisesGroup(ValueError, TypeError):
            raise ExceptionGroup("", [ExceptionGroup("", [ValueError(), TypeError()])])
    # but doesn't consider check (otherwise we'd break typing guarantees)
    with fails_raises_group(
        "Raised exception group did not match: \n"
        "The following expected exceptions did not find a match: [<class 'ValueError'>, <class 'TypeError'>]\n"
        "The following raised exceptions did not find a match\n"
        "  ExceptionGroup('', [ValueError(), TypeError()]):\n"
        "    ExceptionGroup('', [ValueError(), TypeError()]) is not of type 'ValueError'\n"
        "    ExceptionGroup('', [ValueError(), TypeError()]) is not of type 'TypeError'\n"
        "Did you mean to use `flatten_subgroups=True`?",
        add_prefix=False,
    ):
        with RaisesGroup(
            ValueError,
            TypeError,
            check=lambda eg: len(eg.exceptions) == 1,
        ):
            raise ExceptionGroup("", [ExceptionGroup("", [ValueError(), TypeError()])])
    # correct number of exceptions, and flatten_subgroups would make it pass
    with fails_raises_group(
        "Raised exception group did not match: ExceptionGroup('', [ValueError()]) is not of type 'ValueError'\n"
        "Did you mean to use `flatten_subgroups=True`?",
        add_prefix=False,
    ):
        with RaisesGroup(ValueError):
            raise ExceptionGroup("", [ExceptionGroup("", [ValueError()])])
    # correct number of exceptions, but flatten_subgroups wouldn't help, so we don't suggest it
    with fails_raises_group(
        "ExceptionGroup('', [TypeError()]) is not of type 'ValueError'"
    ):
        with RaisesGroup(ValueError):
            raise ExceptionGroup("", [ExceptionGroup("", [TypeError()])])

    # flatten_subgroups can be suggested if nested. This will implicitly ask the user to
    # do `RaisesGroup(RaisesGroup(ValueError, flatten_subgroups=True))` which is unlikely
    # to be what they actually want - but I don't think it's worth trying to special-case
    with fails_raises_group(
        "RaisesGroup(ValueError): ExceptionGroup('', [ValueError()]) is not of type 'ValueError'\n"
        "      Did you mean to use `flatten_subgroups=True`?",
    ):
        with RaisesGroup(RaisesGroup(ValueError)):
            raise ExceptionGroup(
                "",
                [ExceptionGroup("", [ExceptionGroup("", [ValueError()])])],
            )


def test_catch_unwrapped_exceptions() -> None:
    # Catches lone exceptions with strict=False
    # just as except* would
    with RaisesGroup(ValueError, allow_unwrapped=True):
        raise ValueError

    # expecting multiple unwrapped exceptions is not possible
    with pytest.raises(
        ValueError,
        match="^You cannot specify multiple exceptions with",
    ):
        RaisesGroup(SyntaxError, ValueError, allow_unwrapped=True)  # type: ignore[call-overload]
    # if users want one of several exception types they need to use a Matcher
    # (which the error message suggests)
    with RaisesGroup(
        Matcher(check=lambda e: isinstance(e, (SyntaxError, ValueError))),
        allow_unwrapped=True,
    ):
        raise ValueError

    # Unwrapped nested `RaisesGroup` is likely a user error, so we raise an error.
    with pytest.raises(ValueError, match="has no effect when expecting"):
        RaisesGroup(RaisesGroup(ValueError), allow_unwrapped=True)  # type: ignore[call-overload]

    # But it *can* be used to check for nesting level +- 1 if they move it to
    # the nested RaisesGroup. Users should probably use `Matcher`s instead though.
    with RaisesGroup(RaisesGroup(ValueError, allow_unwrapped=True)):
        raise ExceptionGroup("", [ExceptionGroup("", [ValueError()])])
    with RaisesGroup(RaisesGroup(ValueError, allow_unwrapped=True)):
        raise ExceptionGroup("", [ValueError()])

    # with allow_unwrapped=False (default) it will not be caught
    with fails_raises_group(
        "ValueError('value error text') is not an exception group, but would match with `allow_unwrapped=True`"
    ):
        with RaisesGroup(ValueError):
            raise ValueError("value error text")

    # allow_unwrapped on its own won't match against nested groups
    # TODO: even with the flatten_subgroups suggestion I feel like this message is a bit confusing. It is not obvious at all that
    # the mentioned ExceptionGroup (bar) is a sub-exception (of "foo"). Same can be said for some other cases.
    with fails_raises_group(
        "ExceptionGroup('bar', [ValueError()]) is not of type 'ValueError'\n"
        "Did you mean to use `flatten_subgroups=True`?",
    ):
        with RaisesGroup(ValueError, allow_unwrapped=True):
            raise ExceptionGroup("foo", [ExceptionGroup("bar", [ValueError()])])

    # for that you need both allow_unwrapped and flatten_subgroups
    with RaisesGroup(ValueError, allow_unwrapped=True, flatten_subgroups=True):
        raise ExceptionGroup("", [ExceptionGroup("", [ValueError()])])

    # code coverage
    with fails_raises_group(
        "Raised exception (group) did not match: TypeError() is not of type 'ValueError'",
        add_prefix=False,
    ):
        with RaisesGroup(ValueError, allow_unwrapped=True):
            raise TypeError
    with fails_raises_group(
        "Raised exception (group) did not match: Matcher(ValueError): TypeError() is not of type 'ValueError'",
        add_prefix=False,
    ):
        with RaisesGroup(Matcher(ValueError), allow_unwrapped=True):
            raise TypeError

    # check we don't (or maybe we should?) suggest unwrapping with nested RaisesGroup
    with fails_raises_group("ValueError() is not an exception group"):
        with RaisesGroup(RaisesGroup(ValueError)):
            raise ValueError


def test_match() -> None:
    # supports match string
    with RaisesGroup(ValueError, match="bar"):
        raise ExceptionGroup("bar", (ValueError(),))

    # now also works with ^$
    with RaisesGroup(ValueError, match="^bar$"):
        raise ExceptionGroup("bar", (ValueError(),))

    # it also includes notes
    with RaisesGroup(ValueError, match="my note"):
        e = ExceptionGroup("bar", (ValueError(),))
        e.add_note("my note")
        raise e

    # and technically you can match it all with ^$
    # but you're probably better off using a Matcher at that point
    with RaisesGroup(ValueError, match="^bar\nmy note$"):
        e = ExceptionGroup("bar", (ValueError(),))
        e.add_note("my note")
        raise e

    with fails_raises_group("Regex pattern 'foo' did not match 'bar'"):
        with RaisesGroup(ValueError, match="foo"):
            raise ExceptionGroup("bar", (ValueError(),))


def test_check() -> None:
    exc = ExceptionGroup("", (ValueError(),))
    with RaisesGroup(ValueError, check=lambda x: x is exc):
        raise exc
    # not using fails_raises_group because we don't use wrap_escape
    with pytest.raises(
        AssertionError,
        match=(
            r"Raised exception group did not match: check <function test_check.<locals>.<lambda> at 0x.*> did not return True for ExceptionGroup\('', \(ValueError\(\),\)\)"
        ),
    ):
        with RaisesGroup(ValueError, check=lambda x: x is exc):
            raise ExceptionGroup("", (ValueError(),))


def test_unwrapped_match_check() -> None:
    def my_check(e: object) -> bool:  # pragma: no cover
        return True

    msg = (
        "`allow_unwrapped=True` bypasses the `match` and `check` parameters"
        " if the exception is unwrapped. If you intended to match/check the"
        " exception you should use a `Matcher` object. If you want to match/check"
        " the exceptiongroup when the exception *is* wrapped you need to"
        " do e.g. `if isinstance(exc.value, ExceptionGroup):"
        " assert RaisesGroup(...).matches(exc.value)` afterwards."
    )
    with pytest.raises(ValueError, match=re.escape(msg)):
        RaisesGroup(ValueError, allow_unwrapped=True, match="foo")  # type: ignore[call-overload]
    with pytest.raises(ValueError, match=re.escape(msg)):
        RaisesGroup(ValueError, allow_unwrapped=True, check=my_check)  # type: ignore[call-overload]

    # Users should instead use a Matcher
    rg = RaisesGroup(Matcher(ValueError, match="^foo$"), allow_unwrapped=True)
    with rg:
        raise ValueError("foo")
    with rg:
        raise ExceptionGroup("", [ValueError("foo")])

    # or if they wanted to match/check the group, do a conditional `.matches()`
    with RaisesGroup(ValueError, allow_unwrapped=True) as exc:
        raise ExceptionGroup("bar", [ValueError("foo")])
    if isinstance(exc.value, ExceptionGroup):  # pragma: no branch
        assert RaisesGroup(ValueError, match="bar").matches(exc.value)


def test_RaisesGroup_matches() -> None:
    rg = RaisesGroup(ValueError)
    assert not rg.matches(None)
    assert not rg.matches(ValueError())
    assert rg.matches(ExceptionGroup("", (ValueError(),)))


def test_message() -> None:
    def check_message(
        message: str,
        body: RaisesGroup[BaseException],
    ) -> None:
        with pytest.raises(
            AssertionError,
            match=f"^DID NOT RAISE any exception, expected {re.escape(message)}$",
        ):
            with body:
                ...

    # basic
    check_message("ExceptionGroup(ValueError)", RaisesGroup(ValueError))
    # multiple exceptions
    check_message(
        "ExceptionGroup(ValueError, ValueError)",
        RaisesGroup(ValueError, ValueError),
    )
    # nested
    check_message(
        "ExceptionGroup(ExceptionGroup(ValueError))",
        RaisesGroup(RaisesGroup(ValueError)),
    )

    # Matcher
    check_message(
        "ExceptionGroup(Matcher(ValueError, match='my_str'))",
        RaisesGroup(Matcher(ValueError, "my_str")),
    )
    check_message(
        "ExceptionGroup(Matcher(match='my_str'))",
        RaisesGroup(Matcher(match="my_str")),
    )

    # BaseExceptionGroup
    check_message(
        "BaseExceptionGroup(KeyboardInterrupt)",
        RaisesGroup(KeyboardInterrupt),
    )
    # BaseExceptionGroup with type inside Matcher
    check_message(
        "BaseExceptionGroup(Matcher(KeyboardInterrupt))",
        RaisesGroup(Matcher(KeyboardInterrupt)),
    )
    # Base-ness transfers to parent containers
    check_message(
        "BaseExceptionGroup(BaseExceptionGroup(KeyboardInterrupt))",
        RaisesGroup(RaisesGroup(KeyboardInterrupt)),
    )
    # but not to child containers
    check_message(
        "BaseExceptionGroup(BaseExceptionGroup(KeyboardInterrupt), ExceptionGroup(ValueError))",
        RaisesGroup(RaisesGroup(KeyboardInterrupt), RaisesGroup(ValueError)),
    )


def test_assert_message() -> None:
    # the message does not need to list all parameters to RaisesGroup, nor all exceptions
    # in the exception group, as those are both visible in the traceback.
    # first fails to match
    with fails_raises_group("TypeError() is not of type 'ValueError'"):
        with RaisesGroup(ValueError):
            raise ExceptionGroup("a", [TypeError()])
    with fails_raises_group(
        "Raised exception group did not match: \n"
        "The following expected exceptions did not find a match: [RaisesGroup(ValueError), RaisesGroup(ValueError, match='a')]\n"
        "The following raised exceptions did not find a match\n"
        "  ExceptionGroup('', [RuntimeError()]):\n"
        "    RaisesGroup(ValueError): RuntimeError() is not of type 'ValueError'\n"
        "    RaisesGroup(ValueError, match='a'): Regex pattern 'a' did not match ''\n"
        "  RuntimeError():\n"
        "    RaisesGroup(ValueError): RuntimeError() is not an exception group\n"
        "    RaisesGroup(ValueError, match='a'): RuntimeError() is not an exception group",
        add_prefix=False,  # to see the full structure
    ):
        with RaisesGroup(RaisesGroup(ValueError), RaisesGroup(ValueError, match="a")):
            raise ExceptionGroup(
                "",
                [ExceptionGroup("", [RuntimeError()]), RuntimeError()],
            )

    with fails_raises_group(
        "Raised exception group did not match: \n"
        "2 matched exceptions. \n"
        "The following expected exceptions did not find a match: [RaisesGroup(RuntimeError), RaisesGroup(ValueError)]\n"
        "The following raised exceptions did not find a match\n"
        "  RuntimeError():\n"
        "    RuntimeError() is not of type 'ValueError'\n"
        "    Matcher(TypeError): RuntimeError() is not of type 'TypeError'\n"
        "    RaisesGroup(RuntimeError): RuntimeError() is not an exception group, but would match with `allow_unwrapped=True`\n"
        "    RaisesGroup(ValueError): RuntimeError() is not an exception group\n"
        "  ValueError('bar'):\n"
        "    RaisesGroup(RuntimeError): ValueError('bar') is not an exception group\n"
        "    RaisesGroup(ValueError): ValueError('bar') is not an exception group, but would match with `allow_unwrapped=True`\n"
        "    It matches <class 'ValueError'> which was paired with ValueError('foo')",
        add_prefix=False,  # to see the full structure
    ):
        with RaisesGroup(
            ValueError,
            Matcher(TypeError),
            RaisesGroup(RuntimeError),
            RaisesGroup(ValueError),
        ):
            raise ExceptionGroup(
                "a",
                [RuntimeError(), TypeError(), ValueError("foo"), ValueError("bar")],
            )

    # TODO: is this one too terse?
    with fails_raises_group(
        "1 matched exception. AssertionError() is not of type 'TypeError'"
    ):
        with RaisesGroup(ValueError, TypeError):
            raise ExceptionGroup("a", [ValueError(), AssertionError()])

    with fails_raises_group(
        "Matcher(ValueError): TypeError() is not of type 'ValueError'"
    ):
        with RaisesGroup(Matcher(ValueError)):
            raise ExceptionGroup("a", [TypeError()])

    # suggest escaping
    with fails_raises_group(
        # TODO: this message should say the *group* didn't match
        "Raised exception group did not match: Regex pattern 'h(ell)o' did not match 'h(ell)o'\n"
        "Did you mean to `re.escape()` the regex?",
        add_prefix=False,  # to see the full structure
    ):
        with RaisesGroup(ValueError, match="h(ell)o"):
            raise ExceptionGroup("h(ell)o", [ValueError()])
    with fails_raises_group(
        # Ideally the "did you mean to re.escape" should be indented twice
        "Matcher(match='h(ell)o'): Regex pattern 'h(ell)o' did not match 'h(ell)o'\n"
        "Did you mean to `re.escape()` the regex?",
    ):
        with RaisesGroup(Matcher(match="h(ell)o")):
            raise ExceptionGroup("", [ValueError("h(ell)o")])

    # TODO: Printing `ExceptionGroup('', [ValueError(), TypeError()])` over and over here is a bit silly
    with fails_raises_group(
        "Raised exception group did not match: \n"
        "The following expected exceptions did not find a match: [<class 'ValueError'>, <class 'ValueError'>, <class 'ValueError'>, <class 'ValueError'>]\n"
        "The following raised exceptions did not find a match\n"
        "  ExceptionGroup('', [ValueError(), TypeError()]):\n"
        "    ExceptionGroup('', [ValueError(), TypeError()]) is not of type 'ValueError'\n"
        "    ExceptionGroup('', [ValueError(), TypeError()]) is not of type 'ValueError'\n"
        "    ExceptionGroup('', [ValueError(), TypeError()]) is not of type 'ValueError'\n"
        "    ExceptionGroup('', [ValueError(), TypeError()]) is not of type 'ValueError'",
        add_prefix=False,  # to see the full structure
    ):
        with RaisesGroup(ValueError, ValueError, ValueError, ValueError):
            raise ExceptionGroup("", [ExceptionGroup("", [ValueError(), TypeError()])])


def test_assert_message_nested() -> None:
    with fails_raises_group(
        "Raised exception group did not match: \n"
        "The following expected exceptions did not find a match: [RaisesGroup(ValueError), RaisesGroup(RaisesGroup(ValueError)), RaisesGroup(Matcher(TypeError, match='foo')), RaisesGroup(TypeError, ValueError)]\n"
        "The following raised exceptions did not find a match\n"
        "  TypeError():\n"
        "    RaisesGroup(ValueError): TypeError() is not an exception group\n"
        "    RaisesGroup(RaisesGroup(ValueError)): TypeError() is not an exception group\n"
        "    RaisesGroup(Matcher(TypeError, match='foo')): TypeError() is not an exception group\n"
        "    RaisesGroup(TypeError, ValueError): TypeError() is not an exception group\n"
        "  ExceptionGroup('', [TypeError()]):\n"
        "    RaisesGroup(ValueError): TypeError() is not of type 'ValueError'\n"
        "    RaisesGroup(RaisesGroup(ValueError)): RaisesGroup(ValueError): TypeError() is not an exception group\n"
        "    RaisesGroup(Matcher(TypeError, match='foo')): Matcher(TypeError, match='foo'): Regex pattern 'foo' did not match ''\n"
        "    RaisesGroup(TypeError, ValueError): 1 matched exception. Too few exceptions raised, found no match for: [<class 'ValueError'>]\n"
        "  ExceptionGroup('', [TypeError(), TypeError()]):\n"
        "    RaisesGroup(ValueError): \n"
        "      The following expected exceptions did not find a match: [<class 'ValueError'>]\n"
        "      The following raised exceptions did not find a match\n"
        "        TypeError():\n"
        "          TypeError() is not of type 'ValueError'\n"
        "        TypeError():\n"
        "          TypeError() is not of type 'ValueError'\n"
        "    RaisesGroup(RaisesGroup(ValueError)): \n"
        "      The following expected exceptions did not find a match: [RaisesGroup(ValueError)]\n"
        "      The following raised exceptions did not find a match\n"
        "        TypeError():\n"
        "          RaisesGroup(ValueError): TypeError() is not an exception group\n"
        "        TypeError():\n"
        "          RaisesGroup(ValueError): TypeError() is not an exception group\n"
        "    RaisesGroup(Matcher(TypeError, match='foo')): \n"
        "      The following expected exceptions did not find a match: [Matcher(TypeError, match='foo')]\n"
        "      The following raised exceptions did not find a match\n"
        "        TypeError():\n"
        "          Matcher(TypeError, match='foo'): Regex pattern 'foo' did not match ''\n"
        "        TypeError():\n"
        "          Matcher(TypeError, match='foo'): Regex pattern 'foo' did not match ''\n"
        "    RaisesGroup(TypeError, ValueError): 1 matched exception. TypeError() is not of type 'ValueError'",
        add_prefix=False,  # to see the full structure
    ):
        with RaisesGroup(
            RaisesGroup(ValueError),
            RaisesGroup(RaisesGroup(ValueError)),
            RaisesGroup(Matcher(TypeError, match="foo")),
            RaisesGroup(TypeError, ValueError),
        ):
            raise ExceptionGroup(
                "",
                [
                    TypeError(),
                    ExceptionGroup("", [TypeError()]),
                    ExceptionGroup("", [TypeError(), TypeError()]),
                ],
            )


def test_matcher() -> None:
    with pytest.raises(
        ValueError,
        match="^You must specify at least one parameter to match on.$",
    ):
        Matcher()  # type: ignore[call-overload]
    with pytest.raises(
        ValueError,
        match=f"^exception_type {re.escape(repr(object))} must be a subclass of BaseException$",
    ):
        Matcher(object)  # type: ignore[type-var]

    with RaisesGroup(Matcher(ValueError)):
        raise ExceptionGroup("", (ValueError(),))
    with fails_raises_group(
        "Matcher(TypeError): ValueError() is not of type 'TypeError'"
    ):
        with RaisesGroup(Matcher(TypeError)):
            raise ExceptionGroup("", (ValueError(),))


def test_matcher_match() -> None:
    with RaisesGroup(Matcher(ValueError, "foo")):
        raise ExceptionGroup("", (ValueError("foo"),))
    with fails_raises_group(
        "Matcher(ValueError, match='foo'): Regex pattern 'foo' did not match 'bar'"
    ):
        with RaisesGroup(Matcher(ValueError, "foo")):
            raise ExceptionGroup("", (ValueError("bar"),))

    # Can be used without specifying the type
    with RaisesGroup(Matcher(match="foo")):
        raise ExceptionGroup("", (ValueError("foo"),))
    with fails_raises_group(
        "Matcher(match='foo'): Regex pattern 'foo' did not match 'bar'"
    ):
        with RaisesGroup(Matcher(match="foo")):
            raise ExceptionGroup("", (ValueError("bar"),))

    # check ^$
    with RaisesGroup(Matcher(ValueError, match="^bar$")):
        raise ExceptionGroup("", [ValueError("bar")])
    with fails_raises_group(
        "Matcher(ValueError, match='^bar$'): Regex pattern '^bar$' did not match 'barr'"
    ):
        with RaisesGroup(Matcher(ValueError, match="^bar$")):
            raise ExceptionGroup("", [ValueError("barr")])


def test_Matcher_check() -> None:
    def check_oserror_and_errno_is_5(e: BaseException) -> bool:
        return isinstance(e, OSError) and e.errno == 5

    with RaisesGroup(Matcher(check=check_oserror_and_errno_is_5)):
        raise ExceptionGroup("", (OSError(5, ""),))

    # specifying exception_type narrows the parameter type to the callable
    def check_errno_is_5(e: OSError) -> bool:
        return e.errno == 5

    with RaisesGroup(Matcher(OSError, check=check_errno_is_5)):
        raise ExceptionGroup("", (OSError(5, ""),))

    # avoid printing overly verbose repr multiple times
    with fails_raises_group(
        f"Matcher(OSError, check={check_errno_is_5!r}): check did not return True for OSError(6, '')"
    ):
        with RaisesGroup(Matcher(OSError, check=check_errno_is_5)):
            raise ExceptionGroup("", (OSError(6, ""),))

    # in nested cases you still get it multiple times though...
    with fails_raises_group(
        f"RaisesGroup(Matcher(OSError, check={check_errno_is_5!r})): Matcher(OSError, check={check_errno_is_5!r}): check did not return True for OSError(6, '')"
    ):
        with RaisesGroup(RaisesGroup(Matcher(OSError, check=check_errno_is_5))):
            raise ExceptionGroup("", [ExceptionGroup("", [OSError(6, "")])])


def test_matcher_tostring() -> None:
    assert str(Matcher(ValueError)) == "Matcher(ValueError)"
    assert str(Matcher(match="[a-z]")) == "Matcher(match='[a-z]')"
    pattern_no_flags = re.compile(r"noflag", 0)
    assert str(Matcher(match=pattern_no_flags)) == "Matcher(match='noflag')"
    pattern_flags = re.compile(r"noflag", re.IGNORECASE)
    assert str(Matcher(match=pattern_flags)) == f"Matcher(match={pattern_flags!r})"
    assert (
        str(Matcher(ValueError, match="re", check=bool))
        == f"Matcher(ValueError, match='re', check={bool!r})"
    )


def test_raisesgroup_tostring() -> None:
    def check_str_and_repr(s: str) -> None:
        evaled = eval(s)
        assert s == str(evaled) == repr(evaled)

    check_str_and_repr("RaisesGroup(ValueError)")
    check_str_and_repr("RaisesGroup(RaisesGroup(ValueError))")
    check_str_and_repr("RaisesGroup(Matcher(ValueError))")
    check_str_and_repr("RaisesGroup(ValueError, allow_unwrapped=True)")
    check_str_and_repr("RaisesGroup(ValueError, match='aoeu')")

    assert (
        str(RaisesGroup(ValueError, match="[a-z]", check=bool))
        == f"RaisesGroup(ValueError, match='[a-z]', check={bool!r})"
    )


def test__ExceptionInfo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        trio.testing._raises_group,
        "ExceptionInfo",
        trio.testing._raises_group._ExceptionInfo,
    )
    with trio.testing.RaisesGroup(ValueError) as excinfo:
        raise ExceptionGroup("", (ValueError("hello"),))
    assert excinfo.type is ExceptionGroup
    assert excinfo.value.exceptions[0].args == ("hello",)
    assert isinstance(excinfo.tb, TracebackType)
