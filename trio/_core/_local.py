from __future__ import annotations

from typing import Generic, TypeVar, overload

# Runvar implementations
import attr

from .._util import Final
from . import _run

T = TypeVar("T")
C = TypeVar("C", bound="_RunVarToken")


class NoValue(object):
    ...


@attr.s(eq=False, hash=False, slots=True)
class _RunVarToken(Generic[T]):
    _no_value = NoValue()

    _var: RunVar[T] = attr.ib()
    previous_value: T | NoValue = attr.ib(default=_no_value)
    redeemed: bool = attr.ib(default=False, init=False)

    @classmethod
    def empty(cls: type[C], var: RunVar[T]) -> C:
        return cls(var)


@attr.s(eq=False, hash=False, slots=True)
class RunVar(Generic[T], metaclass=Final):
    """The run-local variant of a context variable.

    :class:`RunVar` objects are similar to context variable objects,
    except that they are shared across a single call to :func:`trio.run`
    rather than a single task.

    """

    _NO_DEFAULT = NoValue()
    _name: str = attr.ib()
    _default: T | NoValue = attr.ib(default=_NO_DEFAULT)

    @overload
    def get(self, default: T) -> T:
        ...

    @overload
    def get(self, default: NoValue = _NO_DEFAULT) -> T | NoValue:
        ...

    def get(self, default: T | NoValue = _NO_DEFAULT) -> T | NoValue:
        """Gets the value of this :class:`RunVar` for the current run call."""
        try:
            # not typed yet
            return _run.GLOBAL_RUN_CONTEXT.runner._locals[self]  # type: ignore[return-value, index]
        except AttributeError:
            raise RuntimeError("Cannot be used outside of a run context") from None
        except KeyError:
            # contextvars consistency
            if default is not self._NO_DEFAULT:
                return default

            if self._default is not self._NO_DEFAULT:
                return self._default

            raise LookupError(self) from None

    def set(self, value: T) -> _RunVarToken[T]:
        """Sets the value of this :class:`RunVar` for this current run
        call.

        """
        try:
            old_value = self.get()
        except LookupError:
            token: _RunVarToken[T] = _RunVarToken.empty(self)
        else:
            token = _RunVarToken(self, old_value)

        # This can't fail, because if we weren't in Trio context then the
        # get() above would have failed.
        _run.GLOBAL_RUN_CONTEXT.runner._locals[self] = value  # type: ignore[assignment, index]
        return token

    def reset(self, token: _RunVarToken[T]) -> None:
        """Resets the value of this :class:`RunVar` to what it was
        previously specified by the token.

        """
        if token is None:
            raise TypeError("token must not be none")

        if token.redeemed:
            raise ValueError("token has already been used")

        if token._var is not self:
            raise ValueError("token is not for us")

        previous = token.previous_value
        try:
            if previous is _RunVarToken._no_value:
                _run.GLOBAL_RUN_CONTEXT.runner._locals.pop(self)  # type: ignore[arg-type]
            else:
                _run.GLOBAL_RUN_CONTEXT.runner._locals[self] = previous  # type: ignore[index, assignment]
        except AttributeError:
            raise RuntimeError("Cannot be used outside of a run context")

        token.redeemed = True

    def __repr__(self) -> str:
        return f"<RunVar name={self._name!r}>"
