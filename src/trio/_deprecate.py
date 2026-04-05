from __future__ import annotations

import sys
import warnings
from functools import wraps
from typing import TYPE_CHECKING, ClassVar, TypeVar

import attrs

from ._util import final

if TYPE_CHECKING:
    from collections.abc import Callable

    from typing_extensions import ParamSpec

    ArgsT = ParamSpec("ArgsT")

RetT = TypeVar("RetT")


# We want our warnings to be visible by default (at least for now), but we
# also want it to be possible to override that using the -W switch. AFAICT
# this means we cannot inherit from DeprecationWarning, because the only way
# to make it visible by default then would be to add our own filter at import
# time, but that would override -W switches...
class TrioDeprecationWarning(FutureWarning):
    """Warning emitted if you use deprecated Trio functionality.

    While a relatively mature project, Trio remains committed to refining its
    design and improving usability. As part of this, we occasionally deprecate
    or remove functionality that proves suboptimal. If you use Trio, we
    recommend `subscribing to issue #1
    <https://github.com/python-trio/trio/issues/1>`__ to get information about
    upcoming deprecations and other backwards compatibility breaking changes.

    Despite the name, this class currently inherits from
    :class:`FutureWarning`, not :class:`DeprecationWarning`, because until a
    1.0 release, we want these warnings to be visible by default. You can hide
    them by installing a filter or with the ``-W`` switch: see the
    :mod:`warnings` documentation for details.
    """


def _url_for_issue(issue: int) -> str:
    return f"https://github.com/python-trio/trio/issues/{issue}"


def _stringify(thing: object) -> str:
    if hasattr(thing, "__module__") and hasattr(thing, "__qualname__"):
        return f"{thing.__module__}.{thing.__qualname__}"
    return str(thing)


def warn_deprecated(
    thing: object,
    version: str,
    *,
    issue: int | None,
    instead: object,
    stacklevel: int = 2,
    use_triodeprecationwarning: bool = False,
) -> None:
    """Issue a deprecation warning for a Trio feature.

    Args:
      thing: The deprecated object or a string describing it.
      version: The Trio version in which the deprecation was introduced
          (e.g. ``"0.2.0"``).
      issue: The GitHub issue number tracking the deprecation, or None.
      instead: The replacement to suggest, or None if there is no replacement.
      stacklevel: Passed to :func:`warnings.warn`; controls which call frame
          appears in the warning message. The default of ``2`` points at the
          immediate caller of :func:`warn_deprecated`.
      use_triodeprecationwarning: If True, emit a
          :class:`TrioDeprecationWarning` instead of the default
          :class:`DeprecationWarning`.

    """
    stacklevel += 1
    msg = f"{_stringify(thing)} is deprecated since Trio {version}"
    if instead is None:
        msg += " with no replacement"
    else:
        msg += f"; use {_stringify(instead)} instead"
    if issue is not None:
        msg += f" ({_url_for_issue(issue)})"
    if use_triodeprecationwarning:
        warning_class: type[Warning] = TrioDeprecationWarning
    else:
        warning_class = DeprecationWarning
    warnings.warn(warning_class(msg), stacklevel=stacklevel)


# @deprecated("0.2.0", issue=..., instead=...)
# def ...
def deprecated(
    version: str,
    *,
    thing: object = None,
    issue: int | None,
    instead: object,
    use_triodeprecationwarning: bool = False,
) -> Callable[[Callable[ArgsT, RetT]], Callable[ArgsT, RetT]]:
    """Decorator that marks a function as deprecated.

    When the decorated function is called, a deprecation warning is issued
    via :func:`warn_deprecated`. If the function already has a docstring, a
    ``.. deprecated::`` Sphinx directive is automatically appended to it.

    Args:
      version: The Trio version in which the deprecation was introduced
          (e.g. ``"0.2.0"``).
      thing: The name or object to mention in the warning.  Defaults to the
          decorated function itself.
      issue: The GitHub issue number tracking the deprecation, or None.
      instead: The replacement to suggest, or None if there is no replacement.
      use_triodeprecationwarning: If True, emit a
          :class:`TrioDeprecationWarning` instead of :class:`DeprecationWarning`.

    Returns:
      A decorator that wraps the target function with deprecation behaviour.

    Example::

       @deprecated("0.2.0", issue=None, instead=new_function)
       def old_function(...):
           ...

    """

    def do_wrap(fn: Callable[ArgsT, RetT]) -> Callable[ArgsT, RetT]:
        nonlocal thing

        @wraps(fn)
        def wrapper(*args: ArgsT.args, **kwargs: ArgsT.kwargs) -> RetT:
            warn_deprecated(
                thing,
                version,
                instead=instead,
                issue=issue,
                use_triodeprecationwarning=use_triodeprecationwarning,
            )
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
                doc += f"   For details, see `issue #{issue} <{_url_for_issue(issue)}>`__.\n"
            doc += "\n"
            wrapper.__doc__ = doc

        return wrapper

    return do_wrap


def deprecated_alias(
    old_qualname: str,
    new_fn: Callable[ArgsT, RetT],
    version: str,
    *,
    issue: int | None,
) -> Callable[ArgsT, RetT]:
    """Create a deprecated wrapper that forwards calls to *new_fn*.

    Calling the returned callable is equivalent to calling *new_fn*, but also
    issues a deprecation warning attributing the call to *old_qualname*.

    Args:
      old_qualname: The fully-qualified name of the old (deprecated) callable,
          used in the warning message (e.g. ``"trio.old_name"``).
      new_fn: The replacement callable that the alias should forward to.
      version: The Trio version in which the deprecation was introduced.
      issue: The GitHub issue number tracking the deprecation, or None.

    Returns:
      A wrapper callable that emits a deprecation warning and then delegates
      to *new_fn*.

    """

    @deprecated(version, issue=issue, instead=new_fn)
    @wraps(new_fn, assigned=("__module__", "__annotations__"))
    def wrapper(*args: ArgsT.args, **kwargs: ArgsT.kwargs) -> RetT:
        """Deprecated alias."""
        return new_fn(*args, **kwargs)

    wrapper.__qualname__ = old_qualname
    wrapper.__name__ = old_qualname.rpartition(".")[-1]
    return wrapper


@final
@attrs.frozen(slots=False)
class DeprecatedAttribute:
    """Descriptor for a single deprecated module-level attribute.

    Pass instances of this class to :func:`deprecate_attributes` to declare
    that a module attribute is deprecated.  When the attribute is accessed,
    :func:`warn_deprecated` is called automatically.

    Args:
      value: The current value of the attribute to return to callers.
      version: The Trio version in which the deprecation was introduced.
      issue: The GitHub issue number tracking the deprecation, or None.
      instead: The suggested replacement.  Defaults to *value* itself when
          not provided.

    """

    _not_set: ClassVar[object] = object()

    value: object
    version: str
    issue: int | None
    instead: object = _not_set


def deprecate_attributes(
    module_name: str, deprecated_attributes: dict[str, DeprecatedAttribute]
) -> None:
    """Install a ``__getattr__`` hook on *module_name* to warn on deprecated attributes.

    After this function is called, accessing any attribute listed in
    *deprecated_attributes* on the given module will emit a deprecation
    warning via :func:`warn_deprecated` and then return the attribute's value.
    Accessing any other undefined attribute raises :exc:`AttributeError` as
    normal.

    Args:
      module_name: The ``__name__`` of the module to patch (pass
          ``__name__`` from inside the module itself).
      deprecated_attributes: A mapping from attribute name to a
          :class:`DeprecatedAttribute` instance describing the deprecation.

    """

    def __getattr__(name: str) -> object:
        if name in deprecated_attributes:
            info = deprecated_attributes[name]
            instead = info.instead
            if instead is DeprecatedAttribute._not_set:
                instead = info.value
            thing = f"{module_name}.{name}"
            warn_deprecated(thing, info.version, issue=info.issue, instead=instead)
            return info.value

        msg = "module '{}' has no attribute '{}'"
        raise AttributeError(msg.format(module_name, name))

    sys.modules[module_name].__getattr__ = __getattr__  # type: ignore[method-assign]
