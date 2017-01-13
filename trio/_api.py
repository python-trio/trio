import threading
from functools import wraps

GLOBAL_RUN_CONTEXT = threading.local()

def publish(mod):
    def decorator(fn):
        setattr(mod, fn.__name__, fn)
        mod.__all__.append(fn.__name__)
        return fn

def publish_threadlocal(mod, lookup_path):
    def decorator(fn):
        ns = {}
        exec("""def exported(*args, **kwargs):
                    return fn(_GLOBAL_RUN_CONTEXT.{}, *args, **kwargs)"""
             .format(lookup_path), ns)
        exported = ns["exported"]
        exported = wraps(fn)(exported)
        publish(mod)(exported)
        return fn
    return decorator

def publish_runner_method(mod):
    return publish_threadlocal(mod, "runner")

def publish_iomanager_method(mod):
    return publish_threadlocal(mod, "runner._iomanager")

