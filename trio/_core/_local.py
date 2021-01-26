# Runvar implementations
from typing import Generic, overload, TypeVar, Union

from . import _run

from .._util import Final


_T = TypeVar("_T")


class _NoValue:
    pass


class _RunVarToken(Generic[_T]):
    _no_value = _NoValue()

    __slots__ = ("_var", "previous_value", "redeemed")

    @classmethod
    def empty(cls, var: "RunVar[_T]") -> "_RunVarToken[_T]":
        return cls(var, value=cls._no_value)

    def __init__(self, var: "RunVar", value: Union[_NoValue, _T]):
        self._var = var
        self.previous_value = value
        self.redeemed = False


class _NoDefault:
    pass


class RunVar(Generic[_T], metaclass=Final):
    """The run-local variant of a context variable.

    :class:`RunVar` objects are similar to context variable objects,
    except that they are shared across a single call to :func:`trio.run`
    rather than a single task.

    """

    _NO_DEFAULT = _NoDefault()
    __slots__ = ("_name", "_default")

    @overload
    def __init__(self, name: str) -> None:
        ...

    @overload
    def __init__(self, name: str, default: _T):
        ...

    def __init__(self, name: str, default: object = _NO_DEFAULT) -> None:
        self._name = name
        self._default = default

    def get(self, default: Union[_NoDefault, _T] = _NO_DEFAULT) -> _T:
        """Gets the value of this :class:`RunVar` for the current run call."""

        # Ignoring type hint return complaints since the underlying dict can't really
        # be hinted per run local and other options including casting and checking
        # instance types would result in runtime overhead.

        try:
            return _run.GLOBAL_RUN_CONTEXT.runner._locals[self]  # type: ignore[return-value]
        except AttributeError:
            raise RuntimeError("Cannot be used outside of a run context") from None
        except KeyError:
            # contextvars consistency
            if default is not self._NO_DEFAULT:
                return default  # type: ignore[return-value]

            if self._default is not self._NO_DEFAULT:
                return self._default  # type: ignore[return-value]

            raise LookupError(self) from None

    def set(self, value: _T) -> _RunVarToken[_T]:
        """Sets the value of this :class:`RunVar` for this current run
        call.

        """
        try:
            old_value = self.get()
        except LookupError:
            token = _RunVarToken[_T].empty(self)
        else:
            token = _RunVarToken[_T](self, old_value)

        # This can't fail, because if we weren't in Trio context then the
        # get() above would have failed.
        _run.GLOBAL_RUN_CONTEXT.runner._locals[self] = value
        return token

    def reset(self, token: _RunVarToken) -> None:
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
                _run.GLOBAL_RUN_CONTEXT.runner._locals.pop(self)
            else:
                _run.GLOBAL_RUN_CONTEXT.runner._locals[self] = previous
        except AttributeError:
            raise RuntimeError("Cannot be used outside of a run context")

        token.redeemed = True

    def __repr__(self):
        return "<RunVar name={!r}>".format(self._name)
