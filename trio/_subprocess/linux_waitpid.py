import attr
import functools
import os
import outcome
from typing import Any

from .. import _core
from .._sync import Event
from .._threads import run_sync_in_worker_thread


@attr.s
class WaitpidState:
    pid = attr.ib()
    event = attr.ib(default=attr.Factory(Event))
    outcome = attr.ib(default=None)


# https://github.com/python-trio/trio/issues/618
class StubLimiter:
    def release_on_behalf_of(self, x):
        pass

    async def acquire_on_behalf_of(self, x):
        pass


waitpid_limiter = StubLimiter()


# adapted from
# https://github.com/python-trio/trio/issues/4#issuecomment-398967572
async def _task(state: WaitpidState) -> None:
    """The waitpid thread runner task. This must be spawned as a system
    task."""
    partial = functools.partial(
        os.waitpid,  # function
        state.pid,  # pid
        0  # no options
    )

    tresult = await run_sync_in_worker_thread(
        outcome.capture, partial, cancellable=True, limiter=waitpid_limiter
    )
    state.outcome = tresult
    state.event.set()


async def waitpid(pid: int) -> Any:
    """Waits for a child process with the specified PID to finish running."""
    waiter = WaitpidState(pid=pid)
    _core.spawn_system_task(_task, waiter)

    await waiter.event.wait()
    return waiter.outcome.unwrap()
