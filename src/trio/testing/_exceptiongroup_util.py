from __future__ import annotations

import re
import sys
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Generic,
    Optional,
    Pattern,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    final,
    overload,
)

import _pytest
import _pytest._code

if TYPE_CHECKING:
    from typing_extensions import TypeAlias
if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup

E = TypeVar("E", bound=BaseException)
E2 = TypeVar("E2", bound=BaseException)
T = TypeVar("T")
EE: TypeAlias = Union[Type[E], "ExpectedExceptionGroup[E]"]
EEE: TypeAlias = Union[E, Type[E], "ExpectedExceptionGroup[E]"]


# copy-pasting code between here and WIP pytest PR, which doesn't use future annotations
# ruff: noqa: UP007


# inherit from BaseExceptionGroup for the sake of typing the return type of raises.
# Maybe it also works to do
# `if TYPE_CHECKING: ExpectedExceptionGroup = BaseExceptionGroup`
# though then we would probably need to support `raises(ExceptionGroup(...))`
# class ExpectedExceptionGroup(BaseExceptionGroup[E]):
@final
class ExpectedExceptionGroup(Generic[E]):
    # one might consider also accepting `ExpectedExceptionGroup(SyntaxError, ValueError)`
    @overload
    def __init__(self, exceptions: EEE[E], *args: EEE[E]):
        ...

    @overload
    def __init__(self, exceptions: tuple[EEE[E], ...]):
        ...

    def __init__(self, exceptions: EEE[E] | tuple[EEE[E], ...], *args: EEE[E]):
        if isinstance(exceptions, tuple):
            if args:
                raise ValueError(
                    "All arguments must be exceptions if passing multiple positional arguments."
                )
            self.expected_exceptions = exceptions
        else:
            self.expected_exceptions = (exceptions, *args)
        if not all(
            isinstance(exc, (type, BaseException, ExpectedExceptionGroup))
            for exc in self.expected_exceptions
        ):
            raise ValueError(
                "All arguments must be exception instances, types, or ExpectedExceptionGroup."
            )

    # TODO: TypeGuard
    def matches(
        self,
        exc_val: Optional[BaseException],
    ) -> bool:
        if exc_val is None:
            return False
        if not isinstance(exc_val, BaseExceptionGroup):
            return False
        if len(exc_val.exceptions) != len(self.expected_exceptions):
            return False
        remaining_exceptions = list(self.expected_exceptions)
        for e in exc_val.exceptions:
            for rem_e in remaining_exceptions:
                # TODO: how to print string diff on mismatch?
                # Probably accumulate them, and then if fail, print them
                if (
                    (isinstance(rem_e, type) and isinstance(e, rem_e))
                    or (
                        isinstance(e, BaseExceptionGroup)
                        and isinstance(rem_e, ExpectedExceptionGroup)
                        and rem_e.matches(e)
                    )
                    or (
                        isinstance(rem_e, BaseException)
                        and isinstance(e, type(rem_e))
                        and re.search(str(rem_e), str(e))
                    )
                ):
                    remaining_exceptions.remove(rem_e)  # type: ignore # ??
                    break
            else:
                return False
        return True

    # def __str__(self) -> str:
    #    return f"ExceptionGroup{self.expected_exceptions}"
    # str(tuple(...)) seems to call repr
    def __repr__(self) -> str:
        # TODO: [Base]ExceptionGroup
        return f"ExceptionGroup{self.expected_exceptions}"


@overload
def raises(
    expected_exception: Union[type[E], tuple[type[E], ...]],
    *,
    match: Optional[Union[str, Pattern[str]]] = ...,
) -> RaisesContext[E]:
    ...


@overload
def raises(
    expected_exception: Union[
        ExpectedExceptionGroup[E], tuple[ExpectedExceptionGroup[E], ...]
    ],
    *,
    match: Optional[Union[str, Pattern[str]]] = ...,
) -> RaisesContext[BaseExceptionGroup[E]]:
    ...


@overload
def raises(
    expected_exception: tuple[Union[type[E], ExpectedExceptionGroup[E2]], ...],
    *,
    match: Optional[Union[str, Pattern[str]]] = ...,
) -> RaisesContext[Union[E, BaseExceptionGroup[E2]]]:
    ...


@overload
def raises(  # type: ignore[misc]
    expected_exception: Union[type[E], tuple[type[E], ...]],
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> _pytest._code.ExceptionInfo[E]:
    ...


def raises(
    expected_exception: Union[
        type[E],
        ExpectedExceptionGroup[E2],
        tuple[Union[type[E], ExpectedExceptionGroup[E2]], ...],
    ],
    *args: Any,
    **kwargs: Any,
) -> Union[
    RaisesContext[E],
    RaisesContext[BaseExceptionGroup[E2]],
    RaisesContext[Union[E, BaseExceptionGroup[E2]]],
    _pytest._code.ExceptionInfo[E],
]:
    r"""Assert that a code block/function call raises ``expected_exception``
    or raise a failure exception otherwise.

    :kwparam match:
        If specified, a string containing a regular expression,
        or a regular expression object, that is tested against the string
        representation of the exception using :py:func:`re.search`. To match a literal
        string that may contain :std:ref:`special characters <re-syntax>`, the pattern can
        first be escaped with :py:func:`re.escape`.

        (This is only used when :py:func:`pytest.raises` is used as a context manager,
        and passed through to the function otherwise.
        When using :py:func:`pytest.raises` as a function, you can use:
        ``pytest.raises(Exc, func, match="passed on").match("my pattern")``.)

    .. currentmodule:: _pytest._code

    Use ``pytest.raises`` as a context manager, which will capture the exception of the given
    type::

        >>> import pytest
        >>> with pytest.raises(ZeroDivisionError):
        ...    1/0

    If the code block does not raise the expected exception (``ZeroDivisionError`` in the example
    above), or no exception at all, the check will fail instead.

    You can also use the keyword argument ``match`` to assert that the
    exception matches a text or regex::

        >>> with pytest.raises(ValueError, match='must be 0 or None'):
        ...     raise ValueError("value must be 0 or None")

        >>> with pytest.raises(ValueError, match=r'must be \d+$'):
        ...     raise ValueError("value must be 42")

    The context manager produces an :class:`ExceptionInfo` object which can be used to inspect the
    details of the captured exception::

        >>> with pytest.raises(ValueError) as exc_info:
        ...     raise ValueError("value must be 42")
        >>> assert exc_info.type is ValueError
        >>> assert exc_info.value.args[0] == "value must be 42"

    .. note::

       When using ``pytest.raises`` as a context manager, it's worthwhile to
       note that normal context manager rules apply and that the exception
       raised *must* be the final line in the scope of the context manager.
       Lines of code after that, within the scope of the context manager will
       not be executed. For example::

           >>> value = 15
           >>> with pytest.raises(ValueError) as exc_info:
           ...     if value > 10:
           ...         raise ValueError("value must be <= 10")
           ...     assert exc_info.type is ValueError  # this will not execute

       Instead, the following approach must be taken (note the difference in
       scope)::

           >>> with pytest.raises(ValueError) as exc_info:
           ...     if value > 10:
           ...         raise ValueError("value must be <= 10")
           ...
           >>> assert exc_info.type is ValueError

    **Using with** ``pytest.mark.parametrize``

    When using :ref:`pytest.mark.parametrize ref`
    it is possible to parametrize tests such that
    some runs raise an exception and others do not.

    See :ref:`parametrizing_conditional_raising` for an example.

    **Legacy form**

    It is possible to specify a callable by passing a to-be-called lambda::

        >>> raises(ZeroDivisionError, lambda: 1/0)
        <ExceptionInfo ...>

    or you can specify an arbitrary callable with arguments::

        >>> def f(x): return 1/x
        ...
        >>> raises(ZeroDivisionError, f, 0)
        <ExceptionInfo ...>
        >>> raises(ZeroDivisionError, f, x=0)
        <ExceptionInfo ...>

    The form above is fully supported but discouraged for new code because the
    context manager form is regarded as more readable and less error-prone.

    .. note::
        Similar to caught exception objects in Python, explicitly clearing
        local references to returned ``ExceptionInfo`` objects can
        help the Python interpreter speed up its garbage collection.

        Clearing those references breaks a reference cycle
        (``ExceptionInfo`` --> caught exception --> frame stack raising
        the exception --> current frame stack --> local variables -->
        ``ExceptionInfo``) which makes Python keep all objects referenced
        from that cycle (including all local variables in the current
        frame) alive until the next cyclic garbage collection run.
        More detailed information can be found in the official Python
        documentation for :ref:`the try statement <python:try>`.
    """
    __tracebackhide__ = True

    if not expected_exception:
        raise ValueError(
            f"Expected an exception type or a tuple of exception types, but got `{expected_exception!r}`. "
            f"Raising exceptions is already understood as failing the test, so you don't need "
            f"any special code to say 'this should never raise an exception'."
        )

    if isinstance(expected_exception, (type, ExpectedExceptionGroup)):
        expected_exception_tuple: tuple[
            Union[type[E], ExpectedExceptionGroup[E2]], ...
        ] = (expected_exception,)
    else:
        expected_exception_tuple = expected_exception
    for exc in expected_exception_tuple:
        if (
            not isinstance(exc, type) or not issubclass(exc, BaseException)
        ) and not isinstance(exc, ExpectedExceptionGroup):
            msg = "expected exception must be a BaseException type or ExpectedExceptionGroup instance, not {}"  # type: ignore[unreachable]
            not_a = exc.__name__ if isinstance(exc, type) else type(exc).__name__
            raise TypeError(msg.format(not_a))

    message = f"DID NOT RAISE {expected_exception}"

    if not args:
        match: Optional[Union[str, Pattern[str]]] = kwargs.pop("match", None)
        if kwargs:
            msg = "Unexpected keyword arguments passed to pytest.raises: "
            msg += ", ".join(sorted(kwargs))
            msg += "\nUse context-manager form instead?"
            raise TypeError(msg)
        # the ExpectedExceptionGroup -> BaseExceptionGroup swap necessitates an ignore
        return RaisesContext(expected_exception, message, match)  # type: ignore[misc]
    else:
        func = args[0]

        for exc in expected_exception_tuple:
            if isinstance(exc, ExpectedExceptionGroup):
                raise TypeError(
                    "Only contextmanager form is supported for ExpectedExceptionGroup"
                )

        if not callable(func):
            raise TypeError(f"{func!r} object (type: {type(func)}) must be callable")
        try:
            func(*args[1:], **kwargs)
        except expected_exception as e:  # type: ignore[misc]  # TypeError raised for any ExpectedExceptionGroup
            # We just caught the exception - there is a traceback.
            assert e.__traceback__ is not None
            return _pytest._code.ExceptionInfo.from_exc_info(
                (type(e), e, e.__traceback__)
            )
    raise AssertionError(message)


@final
class RaisesContext(Generic[E]):
    def __init__(
        self,
        expected_exception: Union[EE[E], tuple[EE[E], ...]],
        message: str,
        match_expr: Optional[Union[str, Pattern[str]]] = None,
    ) -> None:
        self.expected_exception = expected_exception
        self.message = message
        self.match_expr = match_expr
        self.excinfo: Optional[_pytest._code.ExceptionInfo[E]] = None

    def __enter__(self) -> _pytest._code.ExceptionInfo[E]:
        self.excinfo = _pytest._code.ExceptionInfo.for_later()
        return self.excinfo

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> bool:
        __tracebackhide__ = True
        if exc_type is None:
            raise AssertionError(self.message)
        assert self.excinfo is not None

        if isinstance(self.expected_exception, ExpectedExceptionGroup):
            if not self.expected_exception.matches(exc_val):
                return False
        elif isinstance(self.expected_exception, tuple):
            for expected_exc in self.expected_exception:
                if (
                    isinstance(expected_exc, ExpectedExceptionGroup)
                    and expected_exc.matches(exc_val)
                ) or (
                    isinstance(expected_exc, type)
                    and issubclass(exc_type, expected_exc)
                ):
                    break
            else:
                return False
        elif not issubclass(exc_type, self.expected_exception):
            return False

        # Cast to narrow the exception type now that it's verified.
        exc_info = cast(Tuple[Type[E], E, TracebackType], (exc_type, exc_val, exc_tb))
        self.excinfo.fill_unfilled(exc_info)
        if self.match_expr is not None:
            self.excinfo.match(self.match_expr)
        return True
