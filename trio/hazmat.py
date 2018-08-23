"""
This namespace represents low-level functionality not intended for daily use,
but useful for extending Trio's functionality.
"""

import sys

# This is the union of a subset of trio/_core/ and some things from trio/*.py.
# See comments in trio/__init__.py for details. To make static analysis easier,
# this lists all possible symbols from trio._core, and then we prune those that
# aren't available on this system. After that we add some symbols from trio/*.py.

__all__ = [
    "cancel_shielded_checkpoint",
    "Abort",
    "wait_task_rescheduled",
    "enable_ki_protection",
    "disable_ki_protection",
    "currently_ki_protected",
    "Task",
    "checkpoint",
    "current_task",
    "current_root_task",
    "checkpoint_if_cancelled",
    "spawn_system_task",
    "reschedule",
    "remove_instrument",
    "add_instrument",
    "current_clock",
    "current_statistics",
    "ParkingLot",
    "UnboundedQueue",
    "RunVar",
    "wait_writable",
    "wait_readable",
    "notify_fd_close",
    "wait_socket_readable",
    "wait_socket_writable",
    "notify_socket_close",
    "TrioToken",
    "current_trio_token",
    # kqueue symbols
    "current_kqueue",
    "monitor_kevent",
    "wait_kevent",
    # windows symbols
    "current_iocp",
    "register_with_iocp",
    "wait_overlapped",
    "monitor_completion_key",
]

from . import _core
# Some hazmat symbols are platform specific
for _sym in list(__all__):
    if hasattr(_core, _sym):
        globals()[_sym] = getattr(_core, _sym)
    else:
        # Fool static analysis (at least PyCharm's) into thinking that we're
        # not modifying __all__, so it can trust the static list up above.
        # https://github.com/python-trio/trio/pull/316#issuecomment-328255867
        # This was useful in September 2017. If it's not September 2017 then
        # who knows.
        remove_from_all = __all__.remove
        remove_from_all(_sym)

# Import bits from trio/*.py
if sys.platform.startswith("win"):
    from ._wait_for_object import WaitForSingleObject
    __all__ += ["WaitForSingleObject"]
