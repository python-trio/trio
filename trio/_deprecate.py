from functools import wraps, partial
import warnings

__all__ = ["TrioDeprecationWarning"]


# We want our warnings to be visible by default (at least for now), but we
# also want it to be possible to override that using the -W switch. AFAICT
# this means we cannot inherit from DeprecationWarning, because the only way
# to make it visible by default then would be to add our own filter at import
# time, but that would override -W switches...
class TrioDeprecationWarning(FutureWarning):
    """Warning emitted if you use deprecated Trio functionality.

    As a young project, Trio is currently quite aggressive about deprecating
    and/or removing functionality that we realize was a bad idea. If you use
    Trio, you should subscribe to `issue #1
    <https://github.com/python-trio/trio/issues/1>`__ to get information about
    upcoming deprecations and other backwards compatibility breaking changes.

    Despite the name, this class currently inherits from
    :class:`FutureWarning`, not :class:`DeprecationWarning`, because while
    we're in young-and-aggressive mode we want these warnings to be visible by
    default. You can hide them by installing a filter or with the ``-W``
    switch: see the :mod:`warnings` documentation for details.

    """


def _stringify(thing):
    if hasattr(thing, "__module__") and hasattr(thing, "__qualname__"):
        return "{}.{}".format(thing.__module__, thing.__qualname__)
    return str(thing)


def warn_deprecated(thing, version, *, issue, instead, stacklevel=2):
    stacklevel += 1
    msg = "{} is deprecated since Trio {}".format(_stringify(thing), version)
    if instead is not None:
        msg += "; use {} instead".format(_stringify(instead))
    if issue is not None:
        msg += " (https://github.com/python-trio/trio/issues/{})".format(issue)
    warnings.warn(TrioDeprecationWarning(msg), stacklevel=stacklevel)


# @deprecated("0.2.0", issue=..., instead=...)
# def ...
def deprecated(version, *, thing=None, issue, instead):
    def do_wrap(fn):
        nonlocal thing

        @wraps(fn)
        def wrapper(*args, **kwargs):
            warn_deprecated(thing, version, instead=instead, issue=issue)
            return fn(*args, **kwargs)

        # If our __module__ or __qualname__ get modified, we want to pick up
        # on that, so we read them off the wrapper object instead of the (now
        # hidden) fn object
        if thing is None:
            thing = wrapper

        return wrapper

    return do_wrap


def deprecated_alias(old_qualname, new_fn, version, *, issue):
    @deprecated(version, issue=issue, instead=new_fn)
    @wraps(new_fn)
    def wrapper(*args, **kwargs):
        return new_fn(*args, **kwargs)

    wrapper.__qualname__ = old_qualname
    wrapper.__name__ = old_qualname.rpartition(".")[-1]
    return wrapper
