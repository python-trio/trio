import attr

# Re-exported as trio.hazmat.* and trio.*
__all__ = [
    "UnhandledExceptionError", "TrioInternalError", "RunFinishedError",
    "WouldBlock",
    "Cancelled", "TaskCancelled", "TimeoutCancelled", "PartialResult",
]

class UnhandledExceptionError(Exception):
    """Raised by run() if your code raises an exception in a context where
    there's nowhere else to propagate it to.

    In particular, if a child Task exits with an exception, then it triggers
    one of these.
    """

class TrioInternalError(Exception):
    """Raised by run() if we hit encounter a bug in trio.

    This should never happen! If you get this error, please file a bug.
    """

# Raised by call_soon if you try to queue work to a runner that isn't running
class RunFinishedError(RuntimeError):
    pass

class WouldBlock(Exception):
    pass

# This is very much like the other exceptions that inherit directly from
# BaseException (= SystemExit, KeyboardInterrupt, GeneratorExit)
class Cancelled(BaseException):
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
