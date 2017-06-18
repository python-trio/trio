"""
This module provides utilities to protect against non-awaited coroutine.

Mostly it provide a protector which can install itself with
`sys.set_coroutine_wrapper` and track the creation of all coroutines.

Every now and then we can go over all the coroutines we have reference to, and
check their state. In trio, the trio-runner will do that, at least on every
checkpoint, but that's not the responsibility of this module.

If the coroutine have been awaited at least once, we discard them.

A :class:`CoroProtector` also provide a convenience method
:meth:`await_later(coro)` that return the coroutine unchanged but will ignore it
if not-awaited at next checkpoint.

A default instance of coroutine protector is provided under the attribute `protector`,
and is shared between `trio.run` and the `MultiError.catch`

"""

import sys
import inspect
import textwrap
from ._exceptions import NonAwaitedCoroutines

try:
    from tracemalloc import get_object_traceback as _get_tb
except ImportError: # Not available on, for example, PyPy
    def _get_tb(obj):
        return None


__all__ = ["CoroProtector", "protector"]

################################################################
# Protection against non-awaited coroutines
################################################################

class CoroProtector:
    """
    Protector preventing the creation of non-awaited coroutines
    between two checkpoints.
    """

    def __init__(self):
        self._enabled = True
        self._pending_test = set()
        self._key = object()
        self._previous_coro_wrapper = None

    def _coro_wrapper(self, coro):
        """
        Coroutine wrapper to track creation of coroutines.
        """
        if self._enabled :
            self._pending_test.add(coro)
        if not self._previous_coro_wrapper:
            return coro
        else:
            return self._previous_coro_wrapper(coro)

    def await_later(self, coro):
        """
        Mark a coroutine as safe to no be awaited, and return it.
        """
        self._pending_test.discard(coro)
        return coro


    def install(self):
        """install a coroutine wrapper to track created coroutines.

        If a coroutine wrapper is already set wrap and call it. 
        """
        self._previous_coro_wrapper = sys.get_coroutine_wrapper()
        sys.set_coroutine_wrapper(self._coro_wrapper)

    def uninstall(self):
        assert sys.get_coroutine_wrapper() == self._coro_wrapper
        sys.set_coroutine_wrapper(self._previous_coro_wrapper)

    def has_unawaited_coroutines(self):
        """
        Return whether there are unawaited coroutines.

        Flush all internally tracked awaited coroutine. Does not discard non-awaited
        ones. You need to call `pop_all_unawaited_coroutines` to do that.
        """
        state = inspect.getcoroutinestate
        self._pending_test = {coro for coro in self._pending_test if state(coro) == 'CORO_CREATED'}
        return len(self._pending_test) > 0

    def pop_all_unawaited_coroutines(self, error=True):
        """
        Check that since last invocation no coroutine has been left unawaited.

        Return a list of unawaited coroutines since last call to this function,
        and stop tracking them.
        """
        pending = self._pending_test
        state = inspect.getcoroutinestate
        self._pending_test = set()
        return [coro for coro in pending if state(coro) == 'CORO_CREATED']

    @staticmethod
    def make_non_awaited_coroutines_error(coros):
        """
        Construct a nice NonAwaitedCoroutines error messages with the origin of the
        coroutine if possible.
        """
        err =[]
        for coro in coros:
            tb = _get_tb(coro)
            if tb:
                err.append(' - {coro} ({tb})'.format(coro=coro, tb=tb)) # pragma: no cover
            else:
                err.append(' - {coro}'.format(coro=coro))
        err = '\n'.join(err)
        return NonAwaitedCoroutines(textwrap.dedent(
            '''
            One or more coroutines where not awaited:

            {err}

            Trio has detected that at least a coroutine has not been between awaited
            between this checkpoint point and previous one. This is may be due
            to a missing `await`.
            '''[1:]).format(err=err), coroutines=coros)

protector = CoroProtector()
