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
        """Gets the value of this `RunVar` for the current call
        to :func:`trio.run`."""
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
        """Sets the value of this `RunVar` for the current call to
        :func:`trio.run`.

        Returns a token which may be passed to :meth:`reset` to restore
        the previous value.
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
        """Resets the value of this `RunVar` to the value it had
        before the call to :meth:`set` that returned the given *token*.
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


class TreeVar(metaclass=Final):
    """A "tree variable": like a context variable except that its value
    in a new task is inherited from the new task's parent nursery rather
    than from the new task's spawner.

    `TreeVar` objects support all the same methods and attributes as
    `~contextvars.ContextVar` objects
    (:meth:`~contextvars.ContextVar.get`,
    :meth:`~contextvars.ContextVar.set`,
    :meth:`~contextvars.ContextVar.reset`, and
    `~contextvars.ContextVar.name`), and they are constructed the same
    way. They also provide the additional methods :meth:`being` and
    :meth:`get_in`, documented below.

    Accessing or changing the value of a `TreeVar` outside of a Trio
    task will raise `RuntimeError`. (Exception: :meth:`get_in` still
    works outside of a task, as long as you have a reference to the
    task or nursery of interest.)

    .. note:: `TreeVar` values are not directly stored in the
       `contextvars.Context`, so you can't use `Context.get()
       <contextvars.Context.get>` to access them. If you need the value
       in a context other than your own, use :meth:`get_in`.

    """

    __slots__ = ("_cvar",)

    def __init__(self, name, **default):
        self._cvar = contextvars.ContextVar(name, **default)

    @property
    def name(self):
        """The name of the variable, as passed during construction. Read-only."""
        return self._cvar.name

    def get(self, default=_NO_DEFAULT):
        """Gets the value of this `TreeVar` for the current task.

        If this `TreeVar` has no value in the current task, then
        :meth:`get` returns the *default* specified as argument to
        :meth:`get`, or else the *default* specified when constructing
        the `TreeVar`, or else raises `LookupError`. See the
        documentation of :meth:`contextvars.ContextVar.get` for more
        details.
        """
        # This is effectively an inlining for efficiency of:
        # return _run.current_task()._tree_context.run(self._cvar.get, default)
        try:
            return _run.GLOBAL_RUN_CONTEXT.task._tree_context[self._cvar]
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
        """Sets the value of this `TreeVar` for the current task.  The new
        value will be inherited by nurseries that are later opened in
        this task, so that new tasks can inherit whatever value was
        set when their parent nursery was created.

        Returns a token which may be passed to :meth:`reset` to restore
        the previous value.
        """
        return _run.current_task()._tree_context.run(self._cvar.set, value)

    def reset(self, token):
        """Resets the value of this `TreeVar` to the value it had
        before the call to :meth:`set` that returned the given *token*.

        The *token* must have been obtained from a call to :meth:`set` on
        this same `TreeVar` and in the same task that is now calling
        :meth:`reset`. Also, each *token* may only be used in one call to
        :meth:`reset`. Violating these conditions will raise `ValueError`.
        """
        _run.current_task()._tree_context.run(self._cvar.reset, token)

    @contextmanager
    def being(self, value):
        """Returns a context manager which sets the value of this `TreeVar` to
        *value* upon entry and restores its previous value upon exit.
        """
        token = self.set(value)
        try:
            yield
        finally:
            self.reset(token)

    def get_in(self, task_or_nursery, default=_NO_DEFAULT):
        """Gets the value of this `TreeVar` in the given
        `~trio.lowlevel.Task` or `~trio.Nursery`.

        The value in a task is the value that would be returned by a
        call to :meth:`~contextvars.ContextVar.get` in that task. The
        value in a nursery is the value that would be returned by
        :meth:`~contextvars.ContextVar.get` at the beginning of a new
        child task started in that nursery. The *default* argument has
        the same semantics as it does for :meth:`~contextvars.ContextVar.get`.
        """
        # copy() so this works from a different thread too. It's a
        # cheap and thread-safe operation (just copying one reference)
        # since the underlying context data is immutable.
        defarg = () if default is _NO_DEFAULT else (default,)
        return task_or_nursery._tree_context.copy().run(self._cvar.get, *defarg)

    def __repr__(self):
        return f"<TreeVar name={self.name!r}>"
