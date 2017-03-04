import attr

# Re-exported
__all__ = [
    "TrioInternalError", "RunFinishedError", "WouldBlock",
    "Cancelled", "PartialResult",
]

class TrioInternalError(Exception):
    """Raised by :func:`run` if we encounter a bug in trio, or (possibly) a
    misuse of one of the low-level :mod:`trio.hazmat` APIs.

    This should never happen! If you get this error, please file a bug.

    Unfortunately, if you get this error it also means that all bets are off –
    trio doesn't know what is going on and its normal invariants may be void.
    (For example, we might have "lost track" of a task. Or lost track of all
    tasks.) Again, though, this shouldn't happen.

    """
    pass

TrioInternalError.__module__ = "trio"


class RunFinishedError(RuntimeError):
    """Raised by ``run_in_trio_thread`` and similar functions if the
    corresponding call to :func:`trio.run` has already finished.

    """
    pass

RunFinishedError.__module__ = "trio"


class WouldBlock(Exception):
    """Raised by ``X_nowait`` functions if ``X`` would block.

    """
    pass

WouldBlock.__module__ = "trio"


class Cancelled(BaseException):
    """Raised by blocking calls if the surrounding scope has been cancelled.

    You should let this exception propagate, to be caught by the relevant
    cancel scope. To remind you of this, it inherits from
    :exc:`BaseException`, like :exc:`KeyboardInterrupt` and
    :exc:`SystemExit`.

    .. note::

       In the US it's also common to see this word spelled "canceled", with
       only one "l". This is a `recent
       <https://books.google.com/ngrams/graph?content=canceled%2Ccancelled&year_start=1800&year_end=2000&corpus=5&smoothing=3&direct_url=t1%3B%2Ccanceled%3B%2Cc0%3B.t1%3B%2Ccancelled%3B%2Cc0>`__
       and `US-specific
       <https://books.google.com/ngrams/graph?content=canceled%2Ccancelled&year_start=1800&year_end=2000&corpus=18&smoothing=3&share=&direct_url=t1%3B%2Ccanceled%3B%2Cc0%3B.t1%3B%2Ccancelled%3B%2Cc0>`__
       innovation, and even in the US both forms are still commonly used. So
       for consistency with the rest of the world and with "cancellation"
       (which always has two "l"s), trio uses the two "l" spelling
       everywhere.

    """
    _scope = None

Cancelled.__module__ = "trio"


@attr.s(slots=True, frozen=True)
class PartialResult:
    # XX
    bytes_sent = attr.ib()
