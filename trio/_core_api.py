# The core public API that everything is built on
#
# The public exports of these are through oratorio.* and oratorio.lowlevel.*
# namespaces.

from ._runner import _GLOBAL_RUN_CONTEXT

def current_task():
    return _GLOBAL_RUN_CONTEXT.task

def _current_runner():
    return _GLOBAL_RUN_CONTEXT.runner
