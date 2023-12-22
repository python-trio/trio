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
        self._excinfo = excinfo

    def fill_unfilled(self, exc_info: tuple[type[E], E, TracebackType]) -> None:
        """Fill an unfilled ExceptionInfo created with ``for_later()``."""
        assert self._excinfo is None, "ExceptionInfo was already filled"
        self._excinfo = exc_info

    @classmethod
    def for_later(cls) -> _ExceptionInfo[E]:
        """Return an unfilled ExceptionInfo."""
        return cls(None)

    @property
    def type(self) -> type[E]:
        """The exception class."""
        assert (
            self._excinfo is not None
        ), ".type can only be used after the context manager exits"
        return self._excinfo[0]

    @property
    def value(self) -> E:
        """The exception value."""
        assert (
            self._excinfo is not None
        ), ".value can only be used after the context manager exits"
        return self._excinfo[1]

    @property
    def tb(self) -> TracebackType:
        """The exception raw traceback."""
        assert (
            self._excinfo is not None
        ), ".tb can only be used after the context manager exits"
        return self._excinfo[2]


# this may bite users with type checkers not using pytest, but that should
# be rare and give quite obvious errors in tests trying to do so.
# Ignoring "incorrect import of pytest", it makes sense in this situation.
if TYPE_CHECKING:
    from pytest import ExceptionInfo  # noqa: PT013

else:
    try:
        from pytest import ExceptionInfo  # noqa: PT013
    except ImportError:  # pragma: no cover
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
        if exception_type is not None and not issubclass(exception_type, BaseException):
            raise ValueError(
                f"exception_type {exception_type} must be a subclass of BaseException"
            )
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

    def __str__(self) -> str:
        reqs = []
        if self.exception_type is not None:
            reqs.append(self.exception_type.__name__)
        for req, attr in (("match", self.match), ("check", self.check)):
            if attr is not None:
                reqs.append(f"{req}={attr!r}")
        return f'Matcher({", ".join(reqs)})'


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
    # needed for pyright, since BaseExceptionGroup.__new__ takes two arguments
    if TYPE_CHECKING:

        def __new__(cls, *args: object, **kwargs: object) -> RaisesGroup[E]:
            ...

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
        self.check = check
        self.is_baseexceptiongroup = False

        for exc in self.expected_exceptions:
            if isinstance(exc, RaisesGroup):
                if not strict:
                    raise ValueError(
                        "You cannot specify a nested structure inside a RaisesGroup with"
                        " strict=False"
                    )
                self.is_baseexceptiongroup |= exc.is_baseexceptiongroup
            elif isinstance(exc, Matcher):
                if exc.exception_type is None:
                    continue
                # Matcher __init__ assures it's a subclass of BaseException
                self.is_baseexceptiongroup |= not issubclass(
                    exc.exception_type, Exception
                )
            elif isinstance(exc, type) and issubclass(exc, BaseException):
                self.is_baseexceptiongroup |= not issubclass(exc, Exception)
            else:
                raise ValueError(
                    "Invalid argument {exc} must be exception type, Matcher, or"
                    " RaisesGroup."
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
        assert (
            exc_type is not None
        ), f"DID NOT RAISE any exception, expected {self.expected_type()}"
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
