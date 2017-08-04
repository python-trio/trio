import attr

# Re-exported
__all__ = [
    "TrioInternalError",
    "RunFinishedError",
    "WouldBlock",
    "Cancelled",
    "ResourceBusyError",
]


# Exceptions often get printed as module.Classname. We pretend these are in
# the trio namespace (where they'll eventually end up) so that users get
# better messages.
def pretend_module_is_trio(cls):
    cls.__module__ = "trio"
    return cls


@pretend_module_is_trio
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


@pretend_module_is_trio
class RunFinishedError(RuntimeError):
    """Raised by ``run_in_trio_thread`` and similar functions if the
    corresponding call to :func:`trio.run` has already finished.

    """
    pass


@pretend_module_is_trio
class WouldBlock(Exception):
    """Raised by ``X_nowait`` functions if ``X`` would block.

    """
    pass


@pretend_module_is_trio
class Cancelled(BaseException):
    """Raised by blocking calls if the surrounding scope has been cancelled.

    You should let this exception propagate, to be caught by the relevant
    cancel scope. To remind you of this, it inherits from :exc:`BaseException`
    instead of :exc:`Exception`, just like :exc:`KeyboardInterrupt` and
    :exc:`SystemExit` do. This means that if you write something like::

       try:
           ...
       except Exception:
           ...

    then this *won't* catch a :exc:`Cancelled` exception.

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


@pretend_module_is_trio
class ResourceBusyError(Exception):
    """Raised when a task attempts to use a resource that some other task is
    already using, and this would lead to bugs and nonsense.

    For example, if two tasks try to send data through the same socket at the
    same time, trio will raise :class:`ResourceBusyError` instead of letting
    the data get scrambled.

    """


ResourceBusyError.__module__ = "trio"
