import attr

# Re-exported as trio.hazmat.* and trio.*
__all__ = [
    "TrioInternalError", "RunFinishedError", "WouldBlock", "MultiError",
    "Cancelled", "PartialResult",
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

class MultiError(BaseException):
    def __new__(cls, exceptions):
        if len(exceptions) == 1:
            return exceptions[0]
        else:
            self = BaseException.__new__(cls)
            self.exceptions = exceptions
            return self

    def __str__(self):
        def format_child(exc):
            return "{}: {}".format(exc.__class__.__name__, exc)
        return ", ".join(format_child(exc) for exc in self.exceptions)

    def __repr__(self):
        return "<MultiError: {}>".format(self)

# This is very much like the other exceptions that inherit directly from
# BaseException (= SystemExit, KeyboardInterrupt, GeneratorExit)
class Cancelled(BaseException):
    pass

@attr.s(slots=True, frozen=True)
class PartialResult:
    # XX
    bytes_sent = attr.ib()
