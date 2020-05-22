# Implementations of RunVar and ScopeVar
import contextvars
from contextlib import contextmanager
from . import _run

from .._util import Final, SubclassingDeprecatedIn_v0_15_0


class _RunVarToken:
    _no_value = object()

    __slots__ = ("_var", "previous_value", "redeemed")

    @classmethod
    def empty(cls, var):
        return cls(var, value=cls._no_value)

    def __init__(self, var, value):
        self._var = var
        self.previous_value = value
        self.redeemed = False


_NO_DEFAULT = object()


class RunVar(metaclass=SubclassingDeprecatedIn_v0_15_0):
    """The run-local variant of a context variable.

    :class:`RunVar` objects are similar to context variable objects,
    except that they are shared across a single call to :func:`trio.run`
    rather than a single task.

    """

    __slots__ = ("_name", "_default")

    def __init__(self, name, default=_NO_DEFAULT):
        self._name = name
        self._default = default

    def get(self, default=_NO_DEFAULT):
        """Gets the value of this :class:`RunVar` for the current run call."""
        try:
            return _run.GLOBAL_RUN_CONTEXT.runner._locals[self]
        except AttributeError:
            raise RuntimeError("Cannot be used outside of a run context") from None
        except KeyError:
            # contextvars consistency
            if default is not _NO_DEFAULT:
                return default

            if self._default is not _NO_DEFAULT:
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
        return "<RunVar name={!r}>".format(self._name)


class ScopeVar(metaclass=Final):
    """A "scope variable": like a context variable except that its value
    is inherited by new tasks in a different way.

    In simple terms, `ScopeVar` lets you define your own custom state
    that's inherited in the same way that :ref:`cancel scopes are
    <child-tasks-and-cancellation>`. Ordinary context variables are
    inherited by new tasks based on the environment surrounding the
    :meth:`~trio.Nursery.start_soon` call that created the task.  By
    contrast, scope variables are inherited based on the environment
    surrounding the nursery into which the new task was spawned. This
    difference makes scope variables a better fit than context
    variables for state that naturally propagates down the task tree.

    Some example uses of a `ScopeVar`:

    * Provide access to a resource that is only usable in a certain
      scope.  This might be a nursery, network connection, or anything
      else whose lifetime is bound to a context manager. Tasks that
      run entirely within the resource's lifetime can use it; tasks
      that might keep running past the resource being destroyed won't see
      it at all.

    * Constrain a function's caller-visible behavior, such as what exceptions
      it might throw. The `ScopeVar`\\'s value will be inherited by every
      task whose exceptions might propagate to the point where the value was
      set.

    `ScopeVar` objects support all the same methods as `~contextvars.ContextVar`
    objects, plus the additional methods :meth:`being` and :meth:`get_in`.

    .. note:: `ScopeVar` values are not directly stored in the
       `contextvars.Context`, so you can't use `Context.get()
       <contextvars.Context.get>` to access them; use :meth:`get_in`
       instead, if you need the value in a context other than your own.
    """

    __slots__ = ("_cvar",)

    def __init__(self, name, **default):
        self._cvar = contextvars.ContextVar(name, **default)

    @property
    def name(self):
        """The name of the variable, as passed during construction. Read-only."""
        return self._cvar.name

    def get(self, default=_NO_DEFAULT):
        """Gets the value of this :class:`ScopeVar` for the current task."""
        # This is effectively an inlining for efficiency of:
        # return _run.current_task()._scope_context.run(self._cvar.get, default)
        try:
            return _run.GLOBAL_RUN_CONTEXT.task._scope_context[self._cvar]
        except AttributeError:
            raise RuntimeError("must be called from async context") from None
        except KeyError:
            pass
        # This will always return the default or raise, because we never give
        # self._cvar a value in any context in which we run user code.
        if default is _NO_DEFAULT:
            return self._cvar.get()
        else:
            return self._cvar.get(default)

    def set(self, value):
        """Sets the value of this :class:`ScopeVar` for the current task and
        any tasks that run in child nurseries that it later creates.
        """
        return _run.current_task()._scope_context.run(self._cvar.set, value)

    def reset(self, token):
        """Resets the value of this :class:`ScopeVar` to what it was
        previously, as specified by the token.
        """
        _run.current_task()._scope_context.run(self._cvar.reset, token)

    @contextmanager
    def being(self, value):
        """Returns a context manager which sets the value of this `ScopeVar` to
        *value* upon entry and restores its previous value upon exit.
        """
        token = self.set(value)
        try:
            yield
        finally:
            self.reset(token)

    def get_in(self, task_or_nursery, default=_NO_DEFAULT):
        """Gets the value of this :class:`ScopeVar` for the given task or nursery."""
        defarg = () if default is _NO_DEFAULT else (default,)
        return task_or_nursery._scope_context.run(self._cvar.get, *defarg)

    def __repr__(self):
        return f"<ScopeVar name={self.name!r}>"
