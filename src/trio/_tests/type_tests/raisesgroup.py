"""The typing of RaisesGroup involves a lot of deception and lies, since AFAIK what we
actually want to achieve is ~impossible. This is because we specify what we expect with
instances of RaisesGroup and exception classes, but excinfo.value will be instances of
[Base]ExceptionGroup and instances of exceptions. So we need to "translate" from
RaisesGroup to ExceptionGroup.

The way it currently works is that RaisesGroup[E] corresponds to
ExceptionInfo[BaseExceptionGroup[E]], so the top-level group will be correct. But
RaisesGroup[RaisesGroup[ValueError]] will become
ExceptionInfo[BaseExceptionGroup[RaisesGroup[ValueError]]]. To get around that we specify
RaisesGroup as a subclass of BaseExceptionGroup during type checking - which should mean
that most static type checking for end users should be mostly correct.
"""

from __future__ import annotations

import sys
from typing import Union

from trio.testing import Matcher, RaisesGroup
from typing_extensions import assert_type

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup, ExceptionGroup

# split into functions to isolate the different scopes


def check_inheritance_and_assignments() -> None:
    # Check inheritance
    _: BaseExceptionGroup[ValueError] = RaisesGroup(ValueError)
    _ = RaisesGroup(RaisesGroup(ValueError))  # type: ignore

    a: BaseExceptionGroup[BaseExceptionGroup[ValueError]]
    a = RaisesGroup(RaisesGroup(ValueError))
    a = BaseExceptionGroup("", (BaseExceptionGroup("", (ValueError(),)),))
    assert a


def check_matcher_typevar_default(e: Matcher) -> object:
    assert e.exception_type is not None
    exc: type[BaseException] = e.exception_type
    # this would previously pass, as the type would be `Any`
    e.exception_type().blah()  # type: ignore
    return exc  # Silence Pyright unused var warning


def check_basic_contextmanager() -> None:
    # One level of Group is correctly translated - except it's a BaseExceptionGroup
    # instead of an ExceptionGroup.
    with RaisesGroup(ValueError) as e:
        raise ExceptionGroup("foo", (ValueError(),))
    assert_type(e.value, BaseExceptionGroup[ValueError])


def check_basic_matches() -> None:
    # check that matches gets rid of the naked ValueError in the union
    exc: ExceptionGroup[ValueError] | ValueError = ExceptionGroup("", (ValueError(),))
    if RaisesGroup(ValueError).matches(exc):
        assert_type(exc, BaseExceptionGroup[ValueError])


def check_matches_with_different_exception_type() -> None:
    # This should probably raise some type error somewhere, since
    # ValueError != KeyboardInterrupt
    e: BaseExceptionGroup[KeyboardInterrupt] = BaseExceptionGroup(
        "", (KeyboardInterrupt(),)
    )
    if RaisesGroup(ValueError).matches(e):
        assert_type(e, BaseExceptionGroup[ValueError])


def check_matcher_init() -> None:
    def check_exc(exc: BaseException) -> bool:
        return isinstance(exc, ValueError)

    # Check various combinations of constructor signatures.
    # At least 1 arg must be provided.
    Matcher()  # type: ignore
    Matcher(ValueError)
    Matcher(ValueError, "regex")
    Matcher(ValueError, "regex", check_exc)
    Matcher(exception_type=ValueError)
    Matcher(match="regex")
    Matcher(check=check_exc)
    Matcher(ValueError, match="regex")
    Matcher(match="regex", check=check_exc)

    def check_filenotfound(exc: FileNotFoundError) -> bool:
        return not exc.filename.endswith(".tmp")

    # If exception_type is provided, that narrows the `check` method's argument.
    Matcher(FileNotFoundError, check=check_filenotfound)
    Matcher(ValueError, check=check_filenotfound)  # type: ignore
    Matcher(check=check_filenotfound)  # type: ignore
    Matcher(FileNotFoundError, match="regex", check=check_filenotfound)


def raisesgroup_check_type_narrowing() -> None:
    """Check type narrowing on the `check` argument to `RaisesGroup`.
    All `type: ignore`s are correctly pointing out type errors, except
    where otherwise noted.


    """

    def handle_exc(e: BaseExceptionGroup[BaseException]) -> bool:
        return True

    def handle_kbi(e: BaseExceptionGroup[KeyboardInterrupt]) -> bool:
        return True

    def handle_value(e: BaseExceptionGroup[ValueError]) -> bool:
        return True

    RaisesGroup(BaseException, check=handle_exc)
    RaisesGroup(BaseException, check=handle_kbi)  # type: ignore

    RaisesGroup(Exception, check=handle_exc)
    RaisesGroup(Exception, check=handle_value)  # type: ignore

    RaisesGroup(KeyboardInterrupt, check=handle_exc)
    RaisesGroup(KeyboardInterrupt, check=handle_kbi)
    RaisesGroup(KeyboardInterrupt, check=handle_value)  # type: ignore

    RaisesGroup(ValueError, check=handle_exc)
    RaisesGroup(ValueError, check=handle_kbi)  # type: ignore
    RaisesGroup(ValueError, check=handle_value)

    RaisesGroup(ValueError, KeyboardInterrupt, check=handle_exc)
    RaisesGroup(ValueError, KeyboardInterrupt, check=handle_kbi)  # type: ignore
    RaisesGroup(ValueError, KeyboardInterrupt, check=handle_value)  # type: ignore


def raisesgroup_narrow_baseexceptiongroup() -> None:
    """Check type narrowing specifically for the container exceptiongroup.
    This is not currently working, and after playing around with it for a bit
    I think the only way is to introduce a subclass `NonBaseRaisesGroup`, and overload
    `__new__` in Raisesgroup to return the subclass when exceptions are non-base.
    (or make current class BaseRaisesGroup and introduce RaisesGroup for non-base)
    I encountered problems trying to type this though, see
    https://github.com/python/mypy/issues/17251
    That is probably possible to work around by entirely using `__new__` instead of
    `__init__`, but........ ugh.
    """

    def handle_group(e: ExceptionGroup[Exception]) -> bool:
        return True

    def handle_group_value(e: ExceptionGroup[ValueError]) -> bool:
        return True

    # should work, but BaseExceptionGroup does not get narrowed to ExceptionGroup
    RaisesGroup(ValueError, check=handle_group_value)  # type: ignore

    # should work, but BaseExceptionGroup does not get narrowed to ExceptionGroup
    RaisesGroup(Exception, check=handle_group)  # type: ignore


def check_matcher_transparent() -> None:
    with RaisesGroup(Matcher(ValueError)) as e:
        ...
    _: BaseExceptionGroup[ValueError] = e.value
    assert_type(e.value, BaseExceptionGroup[ValueError])


def check_nested_raisesgroups_contextmanager() -> None:
    with RaisesGroup(RaisesGroup(ValueError)) as excinfo:
        raise ExceptionGroup("foo", (ValueError(),))

    # thanks to inheritance this assignment works
    _: BaseExceptionGroup[BaseExceptionGroup[ValueError]] = excinfo.value
    # and it can mostly be treated like an exceptiongroup
    print(excinfo.value.exceptions[0].exceptions[0])

    # but assert_type reveals the lies
    print(type(excinfo.value))  # would print "ExceptionGroup"
    # typing says it's a BaseExceptionGroup
    assert_type(
        excinfo.value,
        BaseExceptionGroup[RaisesGroup[ValueError]],
    )

    print(type(excinfo.value.exceptions[0]))  # would print "ExceptionGroup"
    # but type checkers are utterly confused
    assert_type(
        excinfo.value.exceptions[0],
        Union[RaisesGroup[ValueError], BaseExceptionGroup[RaisesGroup[ValueError]]],
    )


def check_nested_raisesgroups_matches() -> None:
    """Check nested RaisesGroups with .matches"""
    exc: ExceptionGroup[ExceptionGroup[ValueError]] = ExceptionGroup(
        "", (ExceptionGroup("", (ValueError(),)),)
    )
    # has the same problems as check_nested_raisesgroups_contextmanager
    if RaisesGroup(RaisesGroup(ValueError)).matches(exc):
        assert_type(exc, BaseExceptionGroup[RaisesGroup[ValueError]])


def check_multiple_exceptions_1() -> None:
    a = RaisesGroup(ValueError, ValueError)
    b = RaisesGroup(Matcher(ValueError), Matcher(ValueError))
    c = RaisesGroup(ValueError, Matcher(ValueError))

    d: BaseExceptionGroup[ValueError]
    d = a
    d = b
    d = c
    assert d


def check_multiple_exceptions_2() -> None:
    # This previously failed due to lack of covariance in the TypeVar
    a = RaisesGroup(Matcher(ValueError), Matcher(TypeError))
    b = RaisesGroup(Matcher(ValueError), TypeError)
    c = RaisesGroup(ValueError, TypeError)

    d: BaseExceptionGroup[Exception]
    d = a
    d = b
    d = c
    assert d


def check_raisesgroup_overloads() -> None:
    # allow_unwrapped=True does not allow:
    # multiple exceptions
    RaisesGroup(ValueError, TypeError, allow_unwrapped=True)  # type: ignore
    # nested RaisesGroup
    RaisesGroup(RaisesGroup(ValueError), allow_unwrapped=True)  # type: ignore
    # specifying match
    RaisesGroup(ValueError, match="foo", allow_unwrapped=True)  # type: ignore
    # specifying check
    RaisesGroup(ValueError, check=bool, allow_unwrapped=True)  # type: ignore
    # allowed variants
    RaisesGroup(ValueError, allow_unwrapped=True)
    RaisesGroup(ValueError, allow_unwrapped=True, flatten_subgroups=True)
    RaisesGroup(Matcher(ValueError), allow_unwrapped=True)

    # flatten_subgroups=True does not allow nested RaisesGroup
    RaisesGroup(RaisesGroup(ValueError), flatten_subgroups=True)  # type: ignore
    # but rest is plenty fine
    RaisesGroup(ValueError, TypeError, flatten_subgroups=True)
    RaisesGroup(ValueError, match="foo", flatten_subgroups=True)
    RaisesGroup(ValueError, check=bool, flatten_subgroups=True)
    RaisesGroup(ValueError, flatten_subgroups=True)
    RaisesGroup(Matcher(ValueError), flatten_subgroups=True)

    # if they're both false we can of course specify nested raisesgroup
    RaisesGroup(RaisesGroup(ValueError))
