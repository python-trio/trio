# Runvar implementations
import attr

from . import _run

from .._util import Final


@attr.s(eq=False, hash=False, slots=True)
class _RunVarToken:
    _no_value = object()

    _var = attr.ib()
    previous_value = attr.ib(default=_no_value)
    redeemed = attr.ib(default=False, init=False)

    @classmethod
    def empty(cls, var):
        return cls(var)


@attr.s(eq=False, hash=False, slots=True)
class RunVar(metaclass=Final):
    """The run-local variant of a context variable.

    :class:`RunVar` objects are similar to context variable objects,
    except that they are shared across a single call to :func:`trio.run`
    rather than a single task.

    """

    _NO_DEFAULT = object()
    _name = attr.ib()
    _default = attr.ib(default=_NO_DEFAULT)

    def get(self, default=_NO_DEFAULT):
        """Gets the value of this :class:`RunVar` for the current run call."""
        try:
            return _run.GLOBAL_RUN_CONTEXT.runner._locals[self]
        except AttributeError:
            raise RuntimeError("Cannot be used outside of a run context") from None
        except KeyError:
            # contextvars consistency
            if default is not self._NO_DEFAULT:
                return default

            if self._default is not self._NO_DEFAULT:
                return self._default

            raise LookupError(self) from None

    def set(self, value):
        """Sets the value of this :class:`RunVar` for this current run
        call.

        """
        try:
            old_value = self.get()
        except LookupError:
            token = _RunVarToken.empty(self)
        else:
            token = _RunVarToken(self, old_value)

        # This can't fail, because if we weren't in Trio context then the
        # get() above would have failed.
        _run.GLOBAL_RUN_CONTEXT.runner._locals[self] = value
        return token

    def reset(self, token):
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
        return f"<RunVar name={self._name!r}>"
