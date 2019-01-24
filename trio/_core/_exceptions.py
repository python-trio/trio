import attr


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


class RunFinishedError(RuntimeError):
    """Raised by ``run_in_trio_thread`` and similar functions if the
    corresponding call to :func:`trio.run` has already finished.

    """
    pass


class WouldBlock(Exception):
    """Raised by ``X_nowait`` functions if ``X`` would block.

    """
    pass


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

    Attempting to raise :exc:`Cancelled` yourself will cause a
    :exc:`RuntimeError`. It would not be associated with a cancel scope and thus
    not be caught by Trio. Use
    :meth:`cancel_scope.cancel() <trio.The cancel scope interface.cancel>`
    instead.

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
    __marker = object()

    def __init__(self, _marker=None):
        if _marker is not self.__marker:
            raise RuntimeError(
                'Cancelled should not be raised directly. Use the cancel() '
                'method on your cancel scope.'
            )
        super().__init__()

    @classmethod
    def _init(cls):
        """A private constructor so that a user-created instance of Cancelled
        can raise an appropriate error. see `issue #342
        <https://github.com/python-trio/trio/issues/342>`__.
        """
        return cls(_marker=cls.__marker)


class BusyResourceError(Exception):
    """Raised when a task attempts to use a resource that some other task is
    already using, and this would lead to bugs and nonsense.

    For example, if two tasks try to send data through the same socket at the
    same time, trio will raise :class:`BusyResourceError` instead of letting
    the data get scrambled.

    """


class ClosedResourceError(Exception):
    """Raised when attempting to use a resource after it has been closed.

    Note that "closed" here means that *your* code closed the resource,
    generally by calling a method with a name like ``close`` or ``aclose``, or
    by exiting a context manager. If a problem arises elsewhere – for example,
    because of a network failure, or because a remote peer closed their end of
    a connection – then that should be indicated by a different exception
    class, like :exc:`BrokenResourceError` or an :exc:`OSError` subclass.

    """


class BrokenResourceError(Exception):
    """Raised when an attempt to use a resource fails due to external
    circumstances.

    For example, you might get this if you try to send data on a stream where
    the remote side has already closed the connection.

    You *don't* get this error if *you* closed the resource – in that case you
    get :class:`ClosedResourceError`.

    This exception's ``__cause__`` attribute will often contain more
    information about the underlying error.

    """


class EndOfChannel(Exception):
    """Raised when trying to receive from a :class:`trio.abc.ReceiveChannel`
    that has no more data to receive.

    This is analogous to an "end-of-file" condition, but for channels.

    """
