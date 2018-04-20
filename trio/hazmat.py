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
    "current_root_task",
    "checkpoint_if_cancelled",
    "spawn_system_task",
    "reschedule",
    "remove_instrument",
    "add_instrument",
    "current_clock",
    "current_statistics",
    "wait_writable",
    "wait_readable",
    "ParkingLot",
    "UnboundedQueue",
    "RunLocal",
    "RunVar",
    "wait_socket_readable",
    "wait_socket_writable",
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
    "wait_for_child",
    "ReadFDStream",
    "WriteFDStream",
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
