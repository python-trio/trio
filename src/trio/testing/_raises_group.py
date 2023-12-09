from __future__ import annotations

import re
import sys
from typing import (
    TYPE_CHECKING,
    Callable,
    ContextManager,
    Generic,
    Iterable,
    Pattern,
    TypeVar,
    cast,
)

from trio._util import final

if TYPE_CHECKING:
    from types import TracebackType

    from typing_extensions import TypeGuard

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup

E = TypeVar("E", bound=BaseException)


# minimal version of pytest.ExceptionInfo in case it is not available
@final
class _ExceptionInfo(Generic[E]):
    _excinfo: tuple[type[E], E, TracebackType] | None

    def __init__(self, excinfo: tuple[type[E], E, TracebackType] | None):
        self._exc_info = excinfo

    def fill_unfilled(self, exc_info: tuple[type[E], E, TracebackType]) -> None:
        """Fill an unfilled ExceptionInfo created with ``for_later()``."""
        assert self._excinfo is None, "ExceptionInfo was already filled"
        self._excinfo = exc_info

    @classmethod
    def for_later(cls) -> _ExceptionInfo[E]:
        """Return an unfilled ExceptionInfo."""
        return cls(None)


# this may bite users with type checkers not using pytest, but that should
# be rare and give quite obvious errors in tests trying to do so.
if TYPE_CHECKING:
    from pytest import ExceptionInfo

else:
    try:
        from pytest import ExceptionInfo
    except ImportError:
        ExceptionInfo = _ExceptionInfo


# copied from pytest.ExceptionInfo
def _stringify_exception(exc: BaseException) -> str:
    return "\n".join(
        [
            str(exc),
            *getattr(exc, "__notes__", []),
        ]
    )


@final
class Matcher(Generic[E]):
    def __init__(
        self,
        exception_type: type[E] | None = None,
        match: str | Pattern[str] | None = None,
        check: Callable[[E], bool] | None = None,
    ):
        if exception_type is None and match is None and check is None:
            raise ValueError("You must specify at least one parameter to match on.")
        self.exception_type = exception_type
        self.match = match
        self.check = check

    def matches(self, exception: E) -> TypeGuard[E]:
        if self.exception_type is not None and not isinstance(
            exception, self.exception_type
        ):
            return False
        if self.match is not None and not re.search(
            self.match, _stringify_exception(exception)
        ):
            return False
        if self.check is not None and not self.check(exception):
            return False
        return True


# typing this has been somewhat of a nightmare, with the primary difficulty making
# the return type of __enter__ correct. Ideally it would function like this
# with RaisesGroup(RaisesGroup(ValueError)) as excinfo:
#   ...
# assert_type(excinfo.value, ExceptionGroup[ExceptionGroup[ValueError]])
# in addition to all the simple cases, but getting all the way to the above seems maybe
# impossible. The type being RaisesGroup[RaisesGroup[ValueError]] is probably also fine,
# as long as I add fake properties corresponding to the properties of exceptiongroup. But
# I had trouble with it handling recursive cases properly.

# Current solution settles on the above giving BaseExceptionGroup[RaisesGroup[ValueError]], and it not
# being a type error to do `with RaisesGroup(ValueError()): ...` - but that will error on runtime.
if TYPE_CHECKING:
    SuperClass = BaseExceptionGroup
else:
    SuperClass = Generic


@final
class RaisesGroup(ContextManager[ExceptionInfo[BaseExceptionGroup[E]]], SuperClass[E]):
    def __init__(
        self,
        exceptions: type[E] | Matcher[E] | E,
        *args: type[E] | Matcher[E] | E,
        strict: bool = True,
        match: str | Pattern[str] | None = None,
        check: Callable[[BaseExceptionGroup[E]], bool] | None = None,
    ):
        self.expected_exceptions: tuple[type[E] | Matcher[E] | E, ...] = (
            exceptions,
            *args,
        )
        self.strict = strict
        self.match_expr = match
        # message is read-only in BaseExceptionGroup, which we lie to mypy we inherit from
        self.check = check

        for exc in self.expected_exceptions:
            if not isinstance(exc, (Matcher, RaisesGroup)) and not (
                isinstance(exc, type) and issubclass(exc, BaseException)
            ):
                raise ValueError(
                    "Invalid argument {exc} must be exception type, Matcher, or"
                    " RaisesGroup."
                )
            if isinstance(exc, RaisesGroup) and not strict:
                raise ValueError(
                    "You cannot specify a nested structure inside a RaisesGroup with"
                    " strict=False"
                )

    def __enter__(self) -> ExceptionInfo[BaseExceptionGroup[E]]:
        self.excinfo: ExceptionInfo[BaseExceptionGroup[E]] = ExceptionInfo.for_later()
        return self.excinfo

    def _unroll_exceptions(
        self, exceptions: Iterable[BaseException]
    ) -> Iterable[BaseException]:
        """Used in non-strict mode."""
        res: list[BaseException] = []
        for exc in exceptions:
            if isinstance(exc, BaseExceptionGroup):
                res.extend(self._unroll_exceptions(exc.exceptions))

            else:
                res.append(exc)
        return res

    def matches(
        self,
        exc_val: BaseException | None,
    ) -> TypeGuard[BaseExceptionGroup[E]]:
        if exc_val is None:
            return False
        # TODO: print/raise why a match fails, in a way that works properly in nested cases
        # maybe have a list of strings logging failed matches, that __exit__ can
        # recursively step through and print on a failing match.
        if not isinstance(exc_val, BaseExceptionGroup):
            return False
        if len(exc_val.exceptions) != len(self.expected_exceptions):
            return False
        if self.match_expr is not None and not re.search(
            self.match_expr, _stringify_exception(exc_val)
        ):
            return False
        if self.check is not None and not self.check(exc_val):
            return False
        remaining_exceptions = list(self.expected_exceptions)
        actual_exceptions: Iterable[BaseException] = exc_val.exceptions
        if not self.strict:
            actual_exceptions = self._unroll_exceptions(actual_exceptions)

        # it should be possible to get RaisesGroup.matches typed so as not to
        # need these type: ignores, but I'm not sure that's possible while also having it
        # transparent for the end user.
        for e in actual_exceptions:
            for rem_e in remaining_exceptions:
                if (
                    (isinstance(rem_e, type) and isinstance(e, rem_e))
                    or (
                        isinstance(e, BaseExceptionGroup)
                        and isinstance(rem_e, RaisesGroup)
                        and rem_e.matches(e)
                    )
                    or (
                        isinstance(rem_e, Matcher)
                        and rem_e.matches(e)  # type: ignore[arg-type]
                    )
                ):
                    remaining_exceptions.remove(rem_e)  # type: ignore[arg-type]
                    break
            else:
                return False
        return True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        __tracebackhide__ = True
        assert exc_type is not None, (
            "DID NOT RAISE any exception, expected"
            f" ExceptionGroup{self.expected_exceptions!r}"
        )
        assert (
            self.excinfo is not None
        ), "Internal error - should have been constructed in __enter__"

        if not self.matches(exc_val):
            return False

        # Cast to narrow the exception type now that it's verified.
        exc_info = cast(
            "tuple[type[BaseExceptionGroup[E]], BaseExceptionGroup[E], TracebackType]",
            (exc_type, exc_val, exc_tb),
        )
        self.excinfo.fill_unfilled(exc_info)
        return True

    def __repr__(self) -> str:
        # TODO: [Base]ExceptionGroup
        return f"ExceptionGroup{self.expected_exceptions}"
