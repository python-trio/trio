import attr
import functools
import os
import outcome
from typing import Dict, Any

from . import _core
from ._sync import Event
from ._threads import run_sync_in_worker_thread

# type: Dict[int, WaitpidResult]
_pending_waitpids = {}


@attr.s
class WaitpidResult:
    event = attr.ib(default=attr.Factory(Event))
    outcome = attr.ib(default=None)
    _cached_result = attr.ib(default=None)

    def unwrap(self):
        if self._cached_result is not None:
            if isinstance(self._cached_result, BaseException):
                raise self._cached_result
            return self._cached_result

        try:
            self._cached_result = self.outcome.unwrap()
            return self._cached_result
        except BaseException as e:
            self._cached_result = e
            raise e from None


# https://github.com/python-trio/trio/issues/618
class StubLimiter:
    def release_on_behalf_of(self, x):
        pass

    async def acquire_on_behalf_of(self, x):
        pass


waitpid_limiter = StubLimiter()


# adapted from
# https://github.com/python-trio/trio/issues/4#issuecomment-398967572
async def _task(pid: int) -> None:
    """The waitpid thread runner task. This must be spawned as a system
    task."""
    partial = functools.partial(
        os.waitpid,  # function
        pid,  # pid
        0  # no options
    )
    try:
        tresult = await run_sync_in_worker_thread(
            outcome.capture,
            partial,
            cancellable=True,
            limiter=waitpid_limiter
        )
    except Exception as e:
        result = _pending_waitpids.pop(pid)
        result.outcome = outcome.Error(e)
        result.event.set()
        raise
    else:
        result = _pending_waitpids.pop(pid)
        result.outcome = tresult
        result.event.set()


async def waitpid(pid: int) -> Any:
    """Waits for a child process with the specified PID to finish running."""
    try:
        waiter = _pending_waitpids[pid]
    except KeyError:
        waiter = WaitpidResult()
        _pending_waitpids[pid] = waiter
        _core.spawn_system_task(_task, pid)

    await waiter.event.wait()
    return waiter.unwrap()
