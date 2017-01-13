from functools import update_wrapper as _update_wrapper
import types as _types
from . import _GLOBAL_RUN_CONTEXT
import ._runner
import ._io

__all__ = []

_TEMPLATE = """\
def exported(*args, **kwargs):
    try:
        meth = _GLOBAL_RUN_CONTEXT.{}.{}
    except AttributeError:
        raise RuntimeError("must be called from async context")
    return meth(*args, **kwargs)
"""

def _export_public(cls, path_to_instance):
    for methname, fn in cls.__dict__.items():
        if callable(fn) and getattr(fn, "_public", False):
            # Create a wrapper function that looks up this method in the
            # current thread-local context version of this object, and calls
            # it. exec() is a bit ugly but the resulting code is faster and
            # simpler than doing some loop over getattr.
            ns = {}
            exec(_TEMPLATE.format(path_to_instance, methname), ns)
            exported = ns["exported"]
            # 'fn' is the *unbound* version of the method, but our exported
            # function has the same API as the *bound* version of the
            # method. So create a dummy bound method object:
            bound_fn = _types.MethodType(fn, object())
            # And then set exported function's metadata to match it:
            _update_wrapper(exported, bound_fn)
            # And now export it:
            globals()[methname] = exported
            __all__.append(methname)

_export_public(_runner.Runner, "runner")
_export_public(_io.TheIOManager, "runner.io_manager")

def current_task():
    return _GLOBAL_RUN_CONTEXT.task
__all__.append("current_task")

@types.coroutine
def sched_yield():
    yield
