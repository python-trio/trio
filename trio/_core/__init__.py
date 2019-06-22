"""
This namespace represents the core functionality that has to be built-in
and deal with private internal data structures. Things in this namespace
are publicly available in either trio, trio.hazmat, or trio.testing.
"""

from ._exceptions import (
    TrioInternalError, RunFinishedError, WouldBlock, Cancelled,
    BusyResourceError, ClosedResourceError, BrokenResourceError, EndOfChannel
)

from ._multierror import MultiError

from ._ki import (
    enable_ki_protection, disable_ki_protection, currently_ki_protected
)

# Imports that always exist
from ._run import (
    Task, CancelScope, run, open_nursery, open_cancel_scope, checkpoint,
    current_task, current_effective_deadline, checkpoint_if_cancelled,
    TASK_STATUS_IGNORED, current_statistics, current_trio_token, reschedule,
    remove_instrument, add_instrument, current_clock, current_root_task,
    spawn_system_task, current_time, wait_all_tasks_blocked, wait_readable,
    wait_writable, notify_closing, Nursery
)

# Has to come after _run to resolve a circular import
from ._traps import (
    cancel_shielded_checkpoint, Abort, wait_task_rescheduled,
    temporarily_detach_coroutine_object, permanently_detach_coroutine_object,
    reattach_detached_coroutine_object
)

from ._entry_queue import TrioToken

from ._parking_lot import ParkingLot

from ._unbounded_queue import UnboundedQueue

from ._local import RunVar

# Kqueue imports
try:
    from ._run import (current_kqueue, monitor_kevent, wait_kevent)
except ImportError:
    pass

# Windows imports
try:
    from ._run import (
        monitor_completion_key, current_iocp, register_with_iocp,
        wait_overlapped, write_overlapped, readinto_overlapped
    )
except ImportError:
    pass
