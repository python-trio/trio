import attr

# Re-exported as trio.hazmat.* and trio.*
__all__ = ["InternalError", "WouldBlock",
           "Cancelled", "TaskCancelled", "TimeoutCancelled",
           "SendallPartialResult"]

class TaskCrashedError(Exception):
    pass

class InternalError(Exception):
    pass

class WouldBlock(Exception):
    pass

class Cancelled(Exception):
    partial_result = None
    interrupt = None  # XX

class TaskCancelled(Cancelled):
    pass

class TimeoutCancelled(Cancelled):
    pass

@attr.s(slots=True)
class PartialResult:
    bytes_sent = attr.ib()
