"""
This namespace represents low-level functionality not intended for daily use,
but useful for extending Trio's functionality.
"""

import select as _select
import sys
import typing as _t

# Generally available symbols
from ._core import (
    Abort,
    ParkingLot,
    RunVar,
    Task,
    TrioToken,
    UnboundedQueue,
    add_instrument,
    cancel_shielded_checkpoint,
    checkpoint,
    checkpoint_if_cancelled,
    current_clock,
    current_root_task,
    current_statistics,
    current_task,
    current_trio_token,
    currently_ki_protected,
    disable_ki_protection,
    enable_ki_protection,
    notify_closing,
    permanently_detach_coroutine_object,
    reattach_detached_coroutine_object,
    remove_instrument,
    reschedule,
    spawn_system_task,
    start_guest_run,
    start_thread_soon,
    temporarily_detach_coroutine_object,
    wait_readable,
    wait_task_rescheduled,
    wait_writable,
)
from ._subprocess import open_process

# This is the union of a subset of trio/_core/ and some things from trio/*.py.
# See comments in trio/__init__.py for details. To make static analysis easier,
# this lists all possible symbols from trio._core, and then we prune those that
# aren't available on this system. After that we add some symbols from trio/*.py.


if sys.platform == "win32":
    # Windows symbols
    from ._core import (
        current_iocp,
        monitor_completion_key,
        readinto_overlapped,
        register_with_iocp,
        wait_overlapped,
        write_overlapped,
    )
    from ._wait_for_object import WaitForSingleObject
else:
    # Unix symbols
    from ._unix_pipes import FdStream

    # Kqueue-specific symbols
    if sys.platform != "linux" and (_t.TYPE_CHECKING or not hasattr(_select, "epoll")):
        from ._core import current_kqueue, monitor_kevent, wait_kevent

del sys
