import attr

# Re-exported
__all__ = [
    "TrioInternalError", "RunFinishedError", "WouldBlock",
    "Cancelled", "PartialResult",
]

class TrioInternalError(Exception):
    """Raised by run() if we encounter a bug in trio.

    This should never happen! If you get this error, please file a bug.
    """

TrioInternalError.__module__ = "trio"


# Raised by call_soon if you try to queue work to a runner that isn't running
class RunFinishedError(RuntimeError):
    pass

RunFinishedError.__module__ = "trio"


class WouldBlock(Exception):
    pass

WouldBlock.__module__ = "trio"


# This is very much like the other exceptions that inherit directly from
# BaseException (= SystemExit, KeyboardInterrupt, GeneratorExit)
class Cancelled(BaseException):
    _scope = None

Cancelled.__module__ = "trio"


@attr.s(slots=True, frozen=True)
class PartialResult:
    # XX
    bytes_sent = attr.ib()
