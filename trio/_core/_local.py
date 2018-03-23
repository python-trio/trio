# Task- and Run-local storage
from .._deprecate import deprecated
from . import _run

__all__ = ["TaskLocal", "RunLocal", "RunVar"]

# Our public API is intentionally almost identical to that of threading.local:
# the user allocates a trio.{Task,Run}Local() object, and then can attach
# arbitrary attributes to it. Reading one of these attributes later will
# return the last value that was assigned to this attribute *by code running
# inside the same task or run*.


# This is conceptually a method on _LocalBase, but given the way we're playing
# with attribute access making it a free-standing function is simpler:
def _local_dict(local_obj):
    locals_type = object.__getattribute__(local_obj, "_locals_key")
    try:
        refobj = getattr(_run.GLOBAL_RUN_CONTEXT, locals_type)
    except AttributeError:
        raise RuntimeError("must be called from async context") from None
    try:
        return refobj._locals[local_obj]
    except KeyError:
        new_dict = dict(object.__getattribute__(local_obj, "_defaults"))
        refobj._locals[local_obj] = new_dict
        return new_dict


# Ughhh subclassing I feel so dirty
class _LocalBase:
    __slots__ = ("_defaults",)

    def __init__(self, **kwargs):
        object.__setattr__(self, "_defaults", kwargs)

    def __getattribute__(self, name):
        ld = _local_dict(self)
        if name == "__dict__":
            return ld
        try:
            return ld[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        _local_dict(self)[name] = value

    def __delattr__(self, name):
        try:
            del _local_dict(self)[name]
        except KeyError:
            raise AttributeError(name) from None

    def __dir__(self):
        return list(_local_dict(self))


class TaskLocal(_LocalBase):
    """Task-local storage.

    Instances of this class have no particular attributes or methods. Instead,
    they serve as a blank slate to which you can add whatever attributes you
    like. Modifications made within one task will only be visible to that task
    – with one exception: when you start a new task, then any
    :class:`TaskLocal` attributes that are visible in the task that called
    ``start`` or ``start_soon`` will be inherited by the child. This
    inheritance takes the form of a shallow copy: further changes in the
    parent will *not* affect the child, and changes in the child will not
    affect the parent. (If you're familiar with how environment variables are
    inherited across processes, then :class:`TaskLocal` inheritance is
    somewhat similar.)

    If you're familiar with :class:`threading.local`, then
    :class:`trio.TaskLocal` is very similar, except adapted to work with tasks
    instead of threads, and with the added feature that values are
    automatically inherited across tasks.

    When creating a :class:`TaskLocal` object, you can provide default values
    as keyword arguments::

       local = trio.TaskLocal(a=1)

       async def main():
           # The first time we access the TaskLocal object, the 'a' attribute
           # is already present:
           assert local.a == 1

    The default values are like the default values to functions: they're only
    evaluated once, when the object is created. So you shouldn't use mutable
    objects as defaults -- they'll be shared not just across tasks, but even
    across entirely unrelated runs! For example::

       # Don't do this!!
       local = trio.TaskLocal(a=[])

       async def main():
           assert local.a == []
           local.a.append(1)

       # First time, everything seems to work
       trio.run(main)

       # Second time, the assertion fails, because the first time modified
       # the list object.
       trio.run(main)

    """
    __slots__ = ()
    _locals_key = "task"

    @deprecated("0.4.0", issue=420, instead="contextvars.ContextVar")
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class _RunVarToken(object):
    _no_value = object()

    __slots__ = ("_var", "previous_value", "redeemed")

    @classmethod
    def empty(cls, var):
        return cls(var, value=cls._no_value)

    def __init__(self, var, value):
        self._var = var
        self.previous_value = value
        self.redeemed = False


class RunVar(object):
    """The run-local variant of a context variable.

    :class:`RunVar` objects are similar to context variable objects,
    except that they are shared across a single call to :func:`trio.run`
    rather than a single task.

    """

    _NO_DEFAULT = object()
    __slots__ = ("_name", "_default")

    def __init__(self, name, default=_NO_DEFAULT):
        self._name = name
        self._default = default

    def get(self, default=_NO_DEFAULT):
        """Gets the value of this :class:`RunVar` for the current run call."""
        try:
            return _run.GLOBAL_RUN_CONTEXT.runner._locals[self]
        except AttributeError:
            raise RuntimeError("Cannot be used outside of a run context") \
                from None
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

        try:
            _run.GLOBAL_RUN_CONTEXT.runner._locals[self] = value
        except AttributeError:
            raise RuntimeError("Cannot be used outside of a run context") \
                from None
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
        return ("<RunVar name={!r}>".format(self._name))


class RunLocal(_LocalBase):
    """Run-local storage.

    :class:`RunLocal` objects are very similar to :class:`trio.TaskLocal`
    objects, except that attributes are shared across all the tasks within a
    single call to :func:`trio.run`. They're also very similar to
    :class:`threading.local` objects, except that :class:`RunLocal` objects
    are automatically wiped clean when :func:`trio.run` returns.

    """
    __slots__ = ()
    _locals_key = "runner"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
