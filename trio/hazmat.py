# These are all re-exported from trio._core. See comments in trio/__init__.py
# for details. To make static analysis easier, this lists all possible
# symbols, and then we prune some below if they aren't available on this
# system.
__all__ = [
    "Result",
    "Value",
    "Error",
    "cancel_shielded_checkpoint",
    "Abort",
    "wait_task_rescheduled",
    "enable_ki_protection",
    "disable_ki_protection",
    "currently_ki_protected",
    "Task",
    "checkpoint",
    "current_task",
    "checkpoint_if_cancelled",
    "spawn_system_task",
    "reschedule",
    "current_call_soon_thread_and_signal_safe",
    "wait_writable",
    "wait_readable",
    "ParkingLot",
    "UnboundedQueue",
    "RunLocal",
    "wait_socket_readable",
    "wait_socket_writable",
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
        __all__.remove(_sym)
