from __future__ import annotations

import re
import sys
from re import Pattern
from typing import (
    TYPE_CHECKING,
    Generic,
    Literal,
    cast,
    overload,
)

from trio._util import final

if TYPE_CHECKING:
    import builtins

    # sphinx will *only* work if we use types.TracebackType, and import
    # *inside* TYPE_CHECKING. No other combination works.....
    import types
    from collections.abc import Callable, Sequence

    from _pytest._code.code import ExceptionChainRepr, ReprExceptionInfo, Traceback
    from typing_extensions import TypeAlias, TypeGuard, TypeVar

    # this conditional definition is because we want to allow a TypeVar default
    MatchE = TypeVar(
        "MatchE",
        bound=BaseException,
        default=BaseException,
        covariant=True,
    )
else:
    from typing import TypeVar

    MatchE = TypeVar("MatchE", bound=BaseException, covariant=True)

# RaisesGroup doesn't work with a default.
BaseExcT_co = TypeVar("BaseExcT_co", bound=BaseException, covariant=True)
BaseExcT_1 = TypeVar("BaseExcT_1", bound=BaseException)
BaseExcT_2 = TypeVar("BaseExcT_2", bound=BaseException)
ExcT_1 = TypeVar("ExcT_1", bound=Exception)
ExcT_2 = TypeVar("ExcT_2", bound=Exception)
ExpectedType: TypeAlias = (
    "type[BaseExcT_co] | Matcher[BaseExcT_co] | RaisesGroup[BaseException]"
)

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup, ExceptionGroup


@final
class _ExceptionInfo(Generic[MatchE]):
    """Minimal re-implementation of pytest.ExceptionInfo, only used if pytest is not available. Supports a subset of its features necessary for functionality of :class:`trio.testing.RaisesGroup` and :class:`trio.testing.Matcher`."""

    _excinfo: tuple[type[MatchE], MatchE, types.TracebackType] | None

    def __init__(
        self,
        excinfo: tuple[type[MatchE], MatchE, types.TracebackType] | None,
    ) -> None:
        self._excinfo = excinfo

    def fill_unfilled(
        self,
        exc_info: tuple[type[MatchE], MatchE, types.TracebackType],
    ) -> None:
        """Fill an unfilled ExceptionInfo created with ``for_later()``."""
        assert self._excinfo is None, "ExceptionInfo was already filled"
        self._excinfo = exc_info

    @classmethod
    def for_later(cls) -> _ExceptionInfo[MatchE]:
        """Return an unfilled ExceptionInfo."""
        return cls(None)

    # Note, special cased in sphinx config, since "type" conflicts.
    @property
    def type(self) -> type[MatchE]:
        """The exception class."""
        assert (
            self._excinfo is not None
        ), ".type can only be used after the context manager exits"
        return self._excinfo[0]

    @property
    def value(self) -> MatchE:
        """The exception value."""
        assert (
            self._excinfo is not None
        ), ".value can only be used after the context manager exits"
        return self._excinfo[1]

    @property
    def tb(self) -> types.TracebackType:
        """The exception raw traceback."""
        assert (
            self._excinfo is not None
        ), ".tb can only be used after the context manager exits"
        return self._excinfo[2]

    def exconly(self, tryshort: bool = False) -> str:
        raise NotImplementedError(
            "This is a helper method only available if you use RaisesGroup with the pytest package installed",
        )

    def errisinstance(
        self,
        exc: builtins.type[BaseException] | tuple[builtins.type[BaseException], ...],
    ) -> bool:
        raise NotImplementedError(
            "This is a helper method only available if you use RaisesGroup with the pytest package installed",
        )

    def getrepr(
        self,
        showlocals: bool = False,
        style: str = "long",
        abspath: bool = False,
        tbfilter: bool | Callable[[_ExceptionInfo], Traceback] = True,
        funcargs: bool = False,
        truncate_locals: bool = True,
        chain: bool = True,
    ) -> ReprExceptionInfo | ExceptionChainRepr:
        raise NotImplementedError(
            "This is a helper method only available if you use RaisesGroup with the pytest package installed",
        )


# Type checkers are not able to do conditional types depending on installed packages, so
# we've added signatures for all helpers to _ExceptionInfo, and then always use that.
# If this ends up leading to problems, we can resort to always using _ExceptionInfo and
# users that want to use getrepr/errisinstance/exconly can write helpers on their own, or
# we reimplement them ourselves...or get this merged in upstream pytest.
if TYPE_CHECKING:
    ExceptionInfo = _ExceptionInfo

else:
    try:
        from pytest import ExceptionInfo  # noqa: PT013
    except ImportError:  # pragma: no cover
        ExceptionInfo = _ExceptionInfo


# copied from pytest.ExceptionInfo
def _stringify_exception(exc: BaseException) -> str:
    return "\n".join(
        [
            getattr(exc, "message", str(exc)),
            *getattr(exc, "__notes__", []),
        ],
    )


# String patterns default to including the unicode flag.
_REGEX_NO_FLAGS = re.compile(r"").flags


def _match_pattern(match: Pattern[str]) -> str | Pattern[str]:
    """helper function to remove redundant `re.compile` calls when printing regex"""
    return match.pattern if match.flags == _REGEX_NO_FLAGS else match


def _check_match(match_expr: Pattern[str] | None, e: BaseException) -> str | None:
    if match_expr is not None and not re.search(
        match_expr,
        stringified_exception := _stringify_exception(e),
    ):
        fail_reason = f"Regex pattern {_match_pattern(match_expr)!r} did not match {stringified_exception!r}"
        if _match_pattern(match_expr) == stringified_exception:
            fail_reason += "\nDid you mean to `re.escape()` the regex?"
        return fail_reason
    return None


def _check_repr(check: Callable[[BaseExcT_1], bool]) -> str:
    """Split out so it can be monkeypatched (e.g. by hypothesis)"""
    return repr(check)


def _check_check(
    check: Callable[[BaseExcT_1], bool] | None,
    exception: BaseExcT_1,
    _depth: int,
) -> str | None:
    if check is None:
        return None
    check_repr = "" if _depth != 0 else " " + _check_repr(check)

    if not check(exception):
        return f"check{check_repr} did not return True for {exception!r}"
    return None


def _check_type(
    expected_type: type[BaseException] | None,
    exception: BaseException,
) -> str | None:
    if expected_type is None:
        return None

    if not isinstance(
        exception,
        expected_type,
    ):
        return f"{exception!r} is not of type {expected_type.__name__!r}"
    return None


def _check_expected(
    expected_type: (
        type[BaseException] | Matcher[BaseException] | RaisesGroup[BaseException]
    ),
    exception: BaseException,
    _depth: int = 0,
) -> str | None:
    if isinstance(expected_type, type):
        return _check_type(expected_type, exception)
    res = expected_type.matches(exception, _depth=_depth)  # type: ignore[call-overload]
    if res:
        return None
    assert expected_type.fail_reason is not None
    return f"{expected_type!r}: {expected_type.fail_reason}"


@final
class Matcher(Generic[MatchE]):
    """Helper class to be used together with RaisesGroups when you want to specify requirements on sub-exceptions. Only specifying the type is redundant, and it's also unnecessary when the type is a nested `RaisesGroup` since it supports the same arguments.
    The type is checked with `isinstance`, and does not need to be an exact match. If that is wanted you can use the ``check`` parameter.
    :meth:`trio.testing.Matcher.matches` can also be used standalone to check individual exceptions.

    Examples::

        with RaisesGroups(Matcher(ValueError, match="string"))
            ...
        with RaisesGroups(Matcher(check=lambda x: x.args == (3, "hello"))):
            ...
        with RaisesGroups(Matcher(check=lambda x: type(x) is ValueError)):
            ...

    """

    # At least one of the three parameters must be passed.
    @overload
    def __init__(
        self: Matcher[MatchE],
        exception_type: type[MatchE],
        match: str | Pattern[str] = ...,
        check: Callable[[MatchE], bool] = ...,
    ) -> None: ...

    @overload
    def __init__(
        self: Matcher[BaseException],  # Give E a value.
        *,
        match: str | Pattern[str],
        # If exception_type is not provided, check() must do any typechecks itself.
        check: Callable[[BaseException], bool] = ...,
    ) -> None: ...

    @overload
    def __init__(self, *, check: Callable[[BaseException], bool]) -> None: ...

    def __init__(
        self,
        exception_type: type[MatchE] | None = None,
        match: str | Pattern[str] | None = None,
        check: Callable[[MatchE], bool] | None = None,
    ):
        if exception_type is None and match is None and check is None:
            raise ValueError("You must specify at least one parameter to match on.")
        if exception_type is not None and not issubclass(exception_type, BaseException):
            raise ValueError(
                f"exception_type {exception_type} must be a subclass of BaseException",
            )
        self.exception_type = exception_type
        self.match: Pattern[str] | None
        self._match = match
        if isinstance(match, str):
            self.match = re.compile(match, flags=_REGEX_NO_FLAGS)
        else:
            self.match = match
        self.check = check
        self.fail_reason: str | None = None

    def matches(
        self,
        exception: BaseException,
        *,
        _depth: int = 0,
    ) -> TypeGuard[MatchE]:
        """Check if an exception matches the requirements of this Matcher.
        If it fails, `.fail_reason` will be set.

        Examples::

            assert Matcher(ValueError).matches(my_exception):
            # is equivalent to
            assert isinstance(my_exception, ValueError)

            # this can be useful when checking e.g. the ``__cause__`` of an exception.
            with pytest.raises(ValueError) as excinfo:
                ...
            assert Matcher(SyntaxError, match="foo").matches(excinfo.value.__cause__)
            # above line is equivalent to
            assert isinstance(excinfo.value.__cause__, SyntaxError)
            assert re.search("foo", str(excinfo.value.__cause__)

        """
        self.fail_reason = _check_type(self.exception_type, exception)
        if self.fail_reason is not None:
            return False

        self.fail_reason = _check_match(self.match, exception)
        if self.fail_reason is not None:
            return False

        # If exception_type is None check() accepts BaseException.
        # If non-none, we have done an isinstance check above.
        self.fail_reason = _check_check(self.check, cast(MatchE, exception), _depth)
        return self.fail_reason is None

    def __str__(self) -> str:
        reqs = []
        if self.exception_type is not None:
            reqs.append(self.exception_type.__name__)
        if self.match is not None:
            # If no flags were specified, discard the redundant re.compile() here.
            reqs.append(
                f"match={_match_pattern(self.match)!r}",
            )
        if self.check is not None:
            reqs.append(f"check={self.check!r}")
        return f'Matcher({", ".join(reqs)})'

    def __repr__(self) -> str:
        return self.__str__()


@final
class RaisesGroup(Generic[BaseExcT_co]):
    """Contextmanager for checking for an expected `ExceptionGroup`.
    This works similar to ``pytest.raises``, and a version of it will hopefully be added upstream, after which this can be deprecated and removed. See https://github.com/pytest-dev/pytest/issues/11538


    The catching behaviour differs from :ref:`except* <except_star>` in multiple different ways, being much stricter by default. By using ``allow_unwrapped=True`` and ``flatten_subgroups=True`` you can match ``except*`` fully when expecting a single exception.

    #. All specified exceptions must be present, *and no others*.

       * If you expect a variable number of exceptions you need to use ``pytest.raises(ExceptionGroup)`` and manually check the contained exceptions. Consider making use of :func:`Matcher.matches`.

    #. It will only catch exceptions wrapped in an exceptiongroup by default.

       * With ``allow_unwrapped=True`` you can specify a single expected exception or `Matcher` and it will match the exception even if it is not inside an `ExceptionGroup`. If you expect one of several different exception types you need to use a `Matcher` object.

    #. By default it cares about the full structure with nested `ExceptionGroup`'s. You can specify nested `ExceptionGroup`'s by passing `RaisesGroup` objects as expected exceptions.

       * With ``flatten_subgroups=True`` it will "flatten" the raised `ExceptionGroup`, extracting all exceptions inside any nested :class:`ExceptionGroup`, before matching.

    It currently does not care about the order of the exceptions, so ``RaisesGroups(ValueError, TypeError)`` is equivalent to ``RaisesGroups(TypeError, ValueError)``.

    Examples::

        with RaisesGroups(ValueError):
            raise ExceptionGroup("", (ValueError(),))
        with RaisesGroups(ValueError, ValueError, Matcher(TypeError, match="expected int")):
            ...
        with RaisesGroups(KeyboardInterrupt, match="hello", check=lambda x: type(x) is BaseExceptionGroup):
            ...
        with RaisesGroups(RaisesGroups(ValueError)):
            raise ExceptionGroup("", (ExceptionGroup("", (ValueError(),)),))

        # flatten_subgroups
        with RaisesGroups(ValueError, flatten_subgroups=True):
            raise ExceptionGroup("", (ExceptionGroup("", (ValueError(),)),))

        # allow_unwrapped
        with RaisesGroups(ValueError, allow_unwrapped=True):
            raise ValueError


    `RaisesGroup.matches` can also be used directly to check a standalone exception group.


    The matching algorithm is greedy, which means cases such as this may fail::

        with RaisesGroups(ValueError, Matcher(ValueError, match="hello")):
            raise ExceptionGroup("", (ValueError("hello"), ValueError("goodbye")))

    even though it generally does not care about the order of the exceptions in the group.
    To avoid the above you should specify the first ValueError with a Matcher as well.
    """

    # allow_unwrapped=True requires: singular exception, exception not being
    # RaisesGroup instance, match is None, check is None
    @overload
    def __init__(
        self,
        exception: type[BaseExcT_co] | Matcher[BaseExcT_co],
        *,
        allow_unwrapped: Literal[True],
        flatten_subgroups: bool = False,
    ) -> None: ...

    # flatten_subgroups = True also requires no nested RaisesGroup
    @overload
    def __init__(
        self,
        exception: type[BaseExcT_co] | Matcher[BaseExcT_co],
        *other_exceptions: type[BaseExcT_co] | Matcher[BaseExcT_co],
        flatten_subgroups: Literal[True],
        match: str | Pattern[str] | None = None,
        check: Callable[[BaseExceptionGroup[BaseExcT_co]], bool] | None = None,
    ) -> None: ...

    # simplify the typevars if possible (the following 3 are equivalent but go simpler->complicated)
    # ... the first handles RaisesGroup[ValueError], the second RaisesGroup[ExceptionGroup[ValueError]],
    #     the third RaisesGroup[ValueError | ExceptionGroup[ValueError]].
    # ... otherwise, we will get results like RaisesGroup[ValueError | ExceptionGroup[Never]] (I think)
    #     (technically correct but misleading)
    @overload
    def __init__(
        self: RaisesGroup[ExcT_1],
        exception: type[ExcT_1] | Matcher[ExcT_1],
        *other_exceptions: type[ExcT_1] | Matcher[ExcT_1],
        match: str | Pattern[str] | None = None,
        check: Callable[[ExceptionGroup[ExcT_1]], bool] | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self: RaisesGroup[ExceptionGroup[ExcT_2]],
        exception: RaisesGroup[ExcT_2],
        *other_exceptions: RaisesGroup[ExcT_2],
        match: str | Pattern[str] | None = None,
        check: Callable[[ExceptionGroup[ExceptionGroup[ExcT_2]]], bool] | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self: RaisesGroup[ExcT_1 | ExceptionGroup[ExcT_2]],
        exception: type[ExcT_1] | Matcher[ExcT_1] | RaisesGroup[ExcT_2],
        *other_exceptions: type[ExcT_1] | Matcher[ExcT_1] | RaisesGroup[ExcT_2],
        match: str | Pattern[str] | None = None,
        check: (
            Callable[[ExceptionGroup[ExcT_1 | ExceptionGroup[ExcT_2]]], bool] | None
        ) = None,
    ) -> None: ...

    # same as the above 3 but handling BaseException
    @overload
    def __init__(
        self: RaisesGroup[BaseExcT_1],
        exception: type[BaseExcT_1] | Matcher[BaseExcT_1],
        *other_exceptions: type[BaseExcT_1] | Matcher[BaseExcT_1],
        match: str | Pattern[str] | None = None,
        check: Callable[[BaseExceptionGroup[BaseExcT_1]], bool] | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self: RaisesGroup[BaseExceptionGroup[BaseExcT_2]],
        exception: RaisesGroup[BaseExcT_2],
        *other_exceptions: RaisesGroup[BaseExcT_2],
        match: str | Pattern[str] | None = None,
        check: (
            Callable[[BaseExceptionGroup[BaseExceptionGroup[BaseExcT_2]]], bool] | None
        ) = None,
    ) -> None: ...

    @overload
    def __init__(
        self: RaisesGroup[BaseExcT_1 | BaseExceptionGroup[BaseExcT_2]],
        exception: type[BaseExcT_1] | Matcher[BaseExcT_1] | RaisesGroup[BaseExcT_2],
        *other_exceptions: type[BaseExcT_1]
        | Matcher[BaseExcT_1]
        | RaisesGroup[BaseExcT_2],
        match: str | Pattern[str] | None = None,
        check: (
            Callable[
                [BaseExceptionGroup[BaseExcT_1 | BaseExceptionGroup[BaseExcT_2]]],
                bool,
            ]
            | None
        ) = None,
    ) -> None: ...

    def __init__(
        self: RaisesGroup[ExcT_1 | BaseExcT_1 | BaseExceptionGroup[BaseExcT_2]],
        exception: type[BaseExcT_1] | Matcher[BaseExcT_1] | RaisesGroup[BaseExcT_2],
        *other_exceptions: type[BaseExcT_1]
        | Matcher[BaseExcT_1]
        | RaisesGroup[BaseExcT_2],
        allow_unwrapped: bool = False,
        flatten_subgroups: bool = False,
        match: str | Pattern[str] | None = None,
        check: (
            Callable[[BaseExceptionGroup[BaseExcT_1]], bool]
            | Callable[[ExceptionGroup[ExcT_1]], bool]
            | None
        ) = None,
    ):
        self.expected_exceptions: tuple[
            type[BaseExcT_co] | Matcher[BaseExcT_co] | RaisesGroup[BaseException],
            ...,
        ] = (
            exception,
            *other_exceptions,
        )
        self.allow_unwrapped = allow_unwrapped
        self.flatten_subgroups: bool = flatten_subgroups
        if isinstance(match, str):
            self.match_expr: Pattern[str] | None = re.compile(
                match,
                flags=_REGEX_NO_FLAGS,
            )
        else:
            self.match_expr = match
        self.check = check
        self.is_baseexceptiongroup = False
        self.fail_reason: str | None = None

        if allow_unwrapped and other_exceptions:
            raise ValueError(
                "You cannot specify multiple exceptions with `allow_unwrapped=True.`"
                " If you want to match one of multiple possible exceptions you should"
                " use a `Matcher`."
                " E.g. `Matcher(check=lambda e: isinstance(e, (...)))`",
            )
        if allow_unwrapped and isinstance(exception, RaisesGroup):
            raise ValueError(
                "`allow_unwrapped=True` has no effect when expecting a `RaisesGroup`."
                " You might want it in the expected `RaisesGroup`, or"
                " `flatten_subgroups=True` if you don't care about the structure.",
            )
        if allow_unwrapped and (match is not None or check is not None):
            raise ValueError(
                "`allow_unwrapped=True` bypasses the `match` and `check` parameters"
                " if the exception is unwrapped. If you intended to match/check the"
                " exception you should use a `Matcher` object. If you want to match/check"
                " the exceptiongroup when the exception *is* wrapped you need to"
                " do e.g. `if isinstance(exc.value, ExceptionGroup):"
                " assert RaisesGroup(...).matches(exc.value)` afterwards.",
            )

        # verify `expected_exceptions` and set `self.is_baseexceptiongroup`
        for exc in self.expected_exceptions:
            if isinstance(exc, RaisesGroup):
                if self.flatten_subgroups:
                    raise ValueError(
                        "You cannot specify a nested structure inside a RaisesGroup with"
                        " `flatten_subgroups=True`. The parameter will flatten subgroups"
                        " in the raised exceptiongroup before matching, which would never"
                        " match a nested structure.",
                    )
                self.is_baseexceptiongroup |= exc.is_baseexceptiongroup
            elif isinstance(exc, Matcher):
                # The Matcher could match BaseExceptions through the other arguments
                # but `self.is_baseexceptiongroup` is only used for printing.
                if exc.exception_type is None:
                    continue
                # Matcher __init__ assures it's a subclass of BaseException
                self.is_baseexceptiongroup |= not issubclass(
                    exc.exception_type,
                    Exception,
                )
            elif isinstance(exc, type) and issubclass(exc, BaseException):
                self.is_baseexceptiongroup |= not issubclass(exc, Exception)
            else:
                raise ValueError(
                    f'Invalid argument "{exc!r}" must be exception type, Matcher, or'
                    " RaisesGroup.",
                )

    @overload
    def __enter__(
        self: RaisesGroup[ExcT_1],
    ) -> ExceptionInfo[ExceptionGroup[ExcT_1]]: ...
    @overload
    def __enter__(
        self: RaisesGroup[BaseExcT_1],
    ) -> ExceptionInfo[BaseExceptionGroup[BaseExcT_1]]: ...

    def __enter__(self) -> ExceptionInfo[BaseExceptionGroup[BaseException]]:
        self.excinfo: ExceptionInfo[BaseExceptionGroup[BaseExcT_co]] = (
            ExceptionInfo.for_later()
        )
        return self.excinfo

    def __str__(self) -> str:
        return self.__repr__()

    def __repr__(self) -> str:
        reqs = [
            e.__name__ if isinstance(e, type) else repr(e)
            for e in self.expected_exceptions
        ]
        if self.allow_unwrapped:
            reqs.append(f"allow_unwrapped={self.allow_unwrapped}")
        if self.flatten_subgroups:
            reqs.append(f"flatten_subgroups={self.flatten_subgroups}")
        if self.match_expr is not None:
            # If no flags were specified, discard the redundant re.compile() here.
            reqs.append(f"match={_match_pattern(self.match_expr)!r}")
        if self.check is not None:
            reqs.append(f"check={self.check!r}")
        return f"RaisesGroup({', '.join(reqs)})"

    def _unroll_exceptions(
        self,
        exceptions: Sequence[BaseException],
    ) -> Sequence[BaseException]:
        """Used if `flatten_subgroups=True`."""
        res: list[BaseException] = []
        for exc in exceptions:
            if isinstance(exc, BaseExceptionGroup):
                res.extend(self._unroll_exceptions(exc.exceptions))

            else:
                res.append(exc)
        return res

    @overload
    def matches(
        self: RaisesGroup[ExcT_1],
        exc_val: BaseException | None,
    ) -> TypeGuard[ExceptionGroup[ExcT_1]]: ...
    @overload
    def matches(
        self: RaisesGroup[BaseExcT_1],
        exc_val: BaseException | None,
    ) -> TypeGuard[BaseExceptionGroup[BaseExcT_1]]: ...

    def matches(
        self,
        exc_val: BaseException | None,
        _depth: int = 0,
    ) -> TypeGuard[BaseExceptionGroup[BaseExcT_co]]:
        """Check if an exception matches the requirements of this RaisesGroup.

        Example::

            with pytest.raises(TypeError) as excinfo:
                ...
            assert RaisesGroups(ValueError).matches(excinfo.value.__cause__)
            # the above line is equivalent to
            myexc = excinfo.value.__cause
            assert isinstance(myexc, BaseExceptionGroup)
            assert len(myexc.exceptions) == 1
            assert isinstance(myexc.exceptions[0], ValueError)
        """
        self.fail_reason = None
        if exc_val is None:
            self.fail_reason = "exception is None"
            return False
        if not isinstance(exc_val, BaseExceptionGroup):
            not_group_msg = f"{exc_val!r} is not an exception group"
            if len(self.expected_exceptions) > 1:
                self.fail_reason = not_group_msg
                return False
            # if we have 1 expected exception, check if it would work even if
            # allow_unwrapped is not set
            res = _check_expected(self.expected_exceptions[0], exc_val)
            if res is None and self.allow_unwrapped:
                return True

            if res is None:
                self.fail_reason = (
                    f"{not_group_msg}, but would match with `allow_unwrapped=True`"
                )
            elif self.allow_unwrapped:
                self.fail_reason = res
            else:
                self.fail_reason = not_group_msg
            return False

        # TODO: if this fails, we should say the *group* message did not match
        self.fail_reason = _check_match(self.match_expr, exc_val)
        if self.fail_reason is not None:
            return False

        actual_exceptions: Sequence[BaseException] = exc_val.exceptions
        if self.flatten_subgroups:
            actual_exceptions = self._unroll_exceptions(actual_exceptions)

        # do the full check on expected exceptions
        self.fail_reason = self._check_exceptions(
            self.expected_exceptions,
            actual_exceptions,
            _depth=_depth,
        )

        if self.fail_reason is not None:
            # if we're not expecting a nested structure, and there is one, do a second
            # pass where we try flattening it
            if (
                not self.flatten_subgroups
                and not any(
                    isinstance(e, RaisesGroup) for e in self.expected_exceptions
                )
                and any(isinstance(e, BaseExceptionGroup) for e in actual_exceptions)
                and self._check_exceptions(
                    self.expected_exceptions,
                    self._unroll_exceptions(exc_val.exceptions),
                    _depth=_depth,
                )
                is None
            ):
                self.fail_reason += (
                    f"\n{_depth * '  '}Did you mean to use `flatten_subgroups=True`?"
                )
            return False

        # only run `self.check` once we know `exc_val` is correct.
        # _check_exceptions does not use TypeGuard, since we want to communicate the fail
        # reason, so we need a type: ignore
        # TODO: if this fails, we should say the *group* did not match
        self.fail_reason = _check_check(self.check, exc_val, _depth)  # type: ignore[arg-type]

        return self.fail_reason is None

    def _check_exceptions(
        self,
        expected_exceptions: tuple[
            ExpectedType[BaseExcT_co],
            ...,
        ],
        actual_exceptions: Sequence[BaseException],
        _depth: int,
    ) -> str | None:
        failed_attempts_dict: dict[BaseException, list[str]] = {}

        remaining_exceptions = list(self.expected_exceptions)
        succesful_matches: dict[ExpectedType[BaseExcT_co], BaseException] = {}
        for e in actual_exceptions:
            failed_attempts_dict[e] = []
            for rem_e in remaining_exceptions:
                res = _check_expected(rem_e, e, _depth=_depth + 3)
                if res is None:
                    succesful_matches[rem_e] = e
                    remaining_exceptions.remove(rem_e)
                    del failed_attempts_dict[e]
                    break
                failed_attempts_dict[e].append(res)

        if not remaining_exceptions and not failed_attempts_dict:
            return None

        succesful_str = (
            ""
            if not succesful_matches
            else f"{len(succesful_matches)} matched exception{'s' if len(succesful_matches) > 1 else ''}. "
        )

        if not remaining_exceptions:
            return f"{succesful_str}Unexpected exception(s): {list(failed_attempts_dict.keys())!r}"
        if not failed_attempts_dict:
            return f"{succesful_str}Too few exceptions raised, found no match for: {remaining_exceptions!r}"

        # in case of a single expected and single raised we simplify the output
        if 1 == len(actual_exceptions) == len(expected_exceptions):
            return f"{succesful_str}{failed_attempts_dict.popitem()[1][0]}"

        # TODO: I'm not 100% sure about printing the exact same as in the case above
        # And in all cases of len(failed_attemts_dict)==1 we probably don't need a full table
        if 1 == len(remaining_exceptions) == len(failed_attempts_dict):
            return f"{succesful_str}{failed_attempts_dict.popitem()[1][0]}"

        curr_indent = " " * 2 * _depth
        s = ""
        if succesful_matches:
            s += f"\n{curr_indent}{succesful_str}"
        s += f"\n{curr_indent}The following expected exceptions did not find a match: {remaining_exceptions!r}"
        s += f"\n{curr_indent}The following raised exceptions did not find a match"
        indent_1 = " " * 2 * (_depth + 1)
        indent_2 = " " * 2 * (_depth + 2)
        for key in failed_attempts_dict:
            s += f"\n{indent_1}{key!r}:"
            for val in failed_attempts_dict[key]:
                s += f"\n{indent_2}{val}"
            for expected, actual_match in succesful_matches.items():
                if _check_expected(expected, key, _depth=0) is None:
                    s += f"\n{indent_2}It matches {expected!r} which was paired with {actual_match!r}"
        return s

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> bool:
        __tracebackhide__ = True
        assert (
            exc_type is not None
        ), f"DID NOT RAISE any exception, expected {self.expected_type()}"
        assert (
            self.excinfo is not None
        ), "Internal error - should have been constructed in __enter__"

        group_str = (
            "[group]"
            if self.allow_unwrapped and not issubclass(exc_type, BaseExceptionGroup)
            else "group"
        )

        assert self.matches(
            exc_val,
        ), f"Raised exception {group_str} did not match: {self.fail_reason}"

        # Cast to narrow the exception type now that it's verified.
        exc_info = cast(
            "tuple[type[BaseExceptionGroup[BaseExcT_co]], BaseExceptionGroup[BaseExcT_co], types.TracebackType]",
            (exc_type, exc_val, exc_tb),
        )
        self.excinfo.fill_unfilled(exc_info)
        return True

    def expected_type(self) -> str:
        subexcs = []
        for e in self.expected_exceptions:
            if isinstance(e, Matcher):
                subexcs.append(str(e))
            elif isinstance(e, RaisesGroup):
                subexcs.append(e.expected_type())
            elif isinstance(e, type):
                subexcs.append(e.__name__)
            else:  # pragma: no cover
                raise AssertionError("unknown type")
        group_type = "Base" if self.is_baseexceptiongroup else ""
        return f"{group_type}ExceptionGroup({', '.join(subexcs)})"
