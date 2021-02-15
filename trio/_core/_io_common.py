import copy
from typing import Optional

import outcome
from .. import _core
from . import _run

from typing_extensions import Protocol


class Waiter(Protocol):
    read_task: Optional[_run.Task]
    write_task: Optional[_run.Task]


# Utility function shared between _io_epoll and _io_windows
def wake_all(waiters: Waiter, exc: Exception) -> None:
    try:
        current_task = _core.current_task()
    except RuntimeError:
        current_task = None
    raise_at_end = False
    for attr_name in ["read_task", "write_task"]:
        task = getattr(waiters, attr_name)
        if task is not None:
            if task is current_task:
                raise_at_end = True
            else:
                _core.reschedule(task, outcome.Error(copy.copy(exc)))
            setattr(waiters, attr_name, None)
    if raise_at_end:
        raise exc
