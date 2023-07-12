from __future__ import annotations

import sys
import warnings
from functools import wraps
from types import ModuleType
from typing import Callable, TypeVar

import attr

T = TypeVar("T")


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


def _url_for_issue(issue):
    return f"https://github.com/python-trio/trio/issues/{issue}"


def _stringify(thing):
    if hasattr(thing, "__module__") and hasattr(thing, "__qualname__"):
        return f"{thing.__module__}.{thing.__qualname__}"
    return str(thing)


def warn_deprecated(thing, version, *, issue, instead, stacklevel=2):
    stacklevel += 1
    msg = f"{_stringify(thing)} is deprecated since Trio {version}"
    if instead is None:
        msg += " with no replacement"
    else:
        msg += f"; use {_stringify(instead)} instead"
    if issue is not None:
        msg += f" ({_url_for_issue(issue)})"
    warnings.warn(TrioDeprecationWarning(msg), stacklevel=stacklevel)


# @deprecated("0.2.0", issue=..., instead=...)
# def ...
def deprecated(
    version: str, *, thing: str | None = None, issue: int, instead: str
) -> Callable[[T], T]:
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

        if wrapper.__doc__ is not None:
            doc = wrapper.__doc__
            doc = doc.rstrip()
            doc += "\n\n"
            doc += f".. deprecated:: {version}\n"
            if instead is not None:
                doc += f"   Use {_stringify(instead)} instead.\n"
            if issue is not None:
                doc += "   For details, see `issue #{} <{}>`__.\n".format(
                    issue, _url_for_issue(issue)
                )
            doc += "\n"
            wrapper.__doc__ = doc

        return wrapper

    return do_wrap


def deprecated_alias(old_qualname, new_fn, version, *, issue):
    @deprecated(version, issue=issue, instead=new_fn)
    @wraps(new_fn, assigned=("__module__", "__annotations__"))
    def wrapper(*args, **kwargs):
        "Deprecated alias."
        return new_fn(*args, **kwargs)

    wrapper.__qualname__ = old_qualname
    wrapper.__name__ = old_qualname.rpartition(".")[-1]
    return wrapper


@attr.s(frozen=True)
class DeprecatedAttribute:
    _not_set = object()

    value = attr.ib()
    version = attr.ib()
    issue = attr.ib()
    instead = attr.ib(default=_not_set)


class _ModuleWithDeprecations(ModuleType):
    def __getattr__(self, name):
        if name in self.__deprecated_attributes__:
            info = self.__deprecated_attributes__[name]
            instead = info.instead
            if instead is DeprecatedAttribute._not_set:
                instead = info.value
            thing = f"{self.__name__}.{name}"
            warn_deprecated(thing, info.version, issue=info.issue, instead=instead)
            return info.value

        msg = "module '{}' has no attribute '{}'"
        raise AttributeError(msg.format(self.__name__, name))


def enable_attribute_deprecations(module_name: str) -> None:
    module = sys.modules[module_name]
    module.__class__ = _ModuleWithDeprecations
    # Make sure that this is always defined so that
    # _ModuleWithDeprecations.__getattr__ can access it without jumping
    # through hoops or risking infinite recursion.
    module.__deprecated_attributes__ = {}  # type: ignore[attr-defined]
