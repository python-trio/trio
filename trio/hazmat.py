"""
This namespace represents low-level functionality not intended for daily use,
but useful for extending Trio's functionality.
"""

import sys

# This is the union of a subset of trio/_core/ and some things from trio/*.py.
# See comments in trio/__init__.py for details. To make static analysis easier,
# this lists all possible symbols from trio._core, and then we prune those that
# aren't available on this system. After that we add some symbols from trio/*.py.

from ._core import (
    cancel_shielded_checkpoint, Abort, wait_task_rescheduled,
    enable_ki_protection, disable_ki_protection, currently_ki_protected, Task,
    checkpoint, current_task, ParkingLot, UnboundedQueue, RunVar,
    wait_writable, wait_readable, notify_fd_close, wait_socket_readable,
    wait_socket_writable, notify_socket_close, TrioToken, current_trio_token,
    temporarily_detach_coroutine_object, permanently_detach_coroutine_object,
    reattach_detached_coroutine_object, current_kqueue, monitor_kevent,
    wait_kevent, current_statistics, reschedule, remove_instrument,
    add_instrument, current_clock, current_root_task, checkpoint_if_cancelled,
    spawn_system_task
)

try:
    from ._core import (
        # windows symbols
        current_iocp,
        register_with_iocp,
        wait_overlapped,
        monitor_completion_key
    )
except ImportError:
    pass

from . import _core

# Some hazmat symbols are platform specific
globals().update(
    {
        _name: _value
        for (_name, _value) in _core.__dict__.items() if _name in [
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
            "temporarily_detach_coroutine_object",
            "permanently_detach_coroutine_object",
            "reattach_detached_coroutine_object",
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
    }
)

# Import bits from trio/*.py
if sys.platform.startswith("win"):
    from ._wait_for_object import WaitForSingleObject
