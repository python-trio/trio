import attr

# Re-exported as trio.hazmat.* and trio.*
__all__ = [
    "TaskCrashedError", "InternalError", "RunFinishedError",
    "WouldBlock",
    "Cancelled", "TaskCancelled", "TimeoutCancelled", "PartialResult",
]

class TaskCrashedError(Exception):
    pass

class InternalError(Exception):
    pass

# Raised by call_soon if you try to queue work to a runner that isn't running
class RunFinishedError(RuntimeError):
    pass

class WouldBlock(Exception):
    pass

class Cancelled(Exception):
    partial_result = None
    _stack_entry = None

class TaskCancelled(Cancelled):
    pass

class TimeoutCancelled(Cancelled):
    pass

@attr.s(slots=True)
class PartialResult:
    # XX
    bytes_sent = attr.ib()
