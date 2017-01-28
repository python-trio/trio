import attr

# Re-exported as trio.hazmat.* and trio.*
__all__ = [
    "TrioInternalError", "RunFinishedError", "WouldBlock",
    "Cancelled", "TaskCancelled", "TimeoutCancelled",
    "KeyboardInterruptCancelled", "PartialResult",
]

class TrioInternalError(Exception):
    """Raised by run() if we hit encounter a bug in trio.

    This should never happen! If you get this error, please file a bug.
    """

# Raised by call_soon if you try to queue work to a runner that isn't running
class RunFinishedError(RuntimeError):
    pass

class WouldBlock(Exception):
    pass

# XX Not sure what this should inherit from.
class MultiError(BaseException):
    def __new__(cls, exceptions):
        # XX should there be some convenience that discards None? what do we
        # return if everything is None?
        # Error checking
        for exc in exceptions:
            if not isinstance(exc, BaseException):
                raise TypeError("expected exception, not {}".format(exc))
        if len(exceptions) == 0:
            raise ValueError("MultiError with 0 exceptions?")
        elif len(exceptions) == 1:
            return exceptions[0]
        else:
            # Combine
            # XX be cleverer about:
            # - chaining, so we get nice tracebacks
            #
            # - disaggregating when there's only 1 exception
            #
            # - maybe: adjust the __bases__ depending on what's present, so
            #   except Exception: works iff all the exceptions inherit from
            #   Exception?  and except Cancelled: works iff there's at least
            #   one Cancelled inside?
            exc = super().__new__()
            exc.exceptions = exceptions

# This is very much like the other exceptions that inherit directly from
# BaseException (= SystemExit, KeyboardInterrupt, GeneratorExit)
class Cancelled(BaseException):
    _scope = None

class TaskCancelled(Cancelled):
    pass

class TimeoutCancelled(Cancelled):
    pass

class KeyboardInterruptCancelled(KeyboardInterrupt, Cancelled):
    pass

@attr.s(slots=True, frozen=True)
class PartialResult:
    # XX
    bytes_sent = attr.ib()
