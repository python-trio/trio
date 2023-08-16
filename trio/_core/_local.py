from __future__ import annotations

from typing import Generic, TypeVar, cast, final

# Runvar implementations
import attr

from .._util import Final, NoPublicConstructor
from . import _run

T = TypeVar("T")


@final
class _NoValue(metaclass=Final):
    ...


@attr.s(eq=False, hash=False, slots=False)
class RunVarToken(Generic[T], metaclass=NoPublicConstructor):
    _var: RunVar[T] = attr.ib()
    previous_value: T | type[_NoValue] = attr.ib(default=_NoValue)
    redeemed: bool = attr.ib(default=False, init=False)

    @classmethod
    def _empty(cls, var: RunVar[T]) -> RunVarToken[T]:
        return cls._create(var)


@attr.s(eq=False, hash=False, slots=True, repr=False)
class RunVar(Generic[T], metaclass=Final):
    """The run-local variant of a context variable.

    :class:`RunVar` objects are similar to context variable objects,
    except that they are shared across a single call to :func:`trio.run`
    rather than a single task.

    """

    _name: str = attr.ib()
    _default: T | type[_NoValue] = attr.ib(default=_NoValue)

    def get(self, default: T | type[_NoValue] = _NoValue) -> T:
        """Gets the value of this :class:`RunVar` for the current run call."""
        try:
            return cast(T, _run.GLOBAL_RUN_CONTEXT.runner._locals[self])
        except AttributeError:
            raise RuntimeError("Cannot be used outside of a run context") from None
        except KeyError:
            # contextvars consistency
            # `type: ignore` awaiting https://github.com/python/mypy/issues/15553 to be fixed & released
            if default is not _NoValue:
                return default  # type: ignore[return-value]

            if self._default is not _NoValue:
                return self._default  # type: ignore[return-value]

            raise LookupError(self) from None

    def set(self, value: T) -> RunVarToken[T]:
        """Sets the value of this :class:`RunVar` for this current run
        call.

        """
        try:
            old_value = self.get()
        except LookupError:
            token = RunVarToken._empty(self)
        else:
            token = RunVarToken[T]._create(self, old_value)

        # This can't fail, because if we weren't in Trio context then the
        # get() above would have failed.
        _run.GLOBAL_RUN_CONTEXT.runner._locals[self] = value  # type: ignore[index,assignment]
        return token

    def reset(self, token: RunVarToken[T]) -> None:
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
            if previous is _NoValue:
                _run.GLOBAL_RUN_CONTEXT.runner._locals.pop(self)
            else:
                _run.GLOBAL_RUN_CONTEXT.runner._locals[self] = previous  # type: ignore[index,assignment]
        except AttributeError:
            raise RuntimeError("Cannot be used outside of a run context")

        token.redeemed = True

    def __repr__(self) -> str:
        return f"<RunVar name={self._name!r}>"
