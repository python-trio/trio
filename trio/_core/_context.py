from async_generator import asynccontextmanager

from . import _run


@asynccontextmanager
async def set_current_context(context):
    """Returns an asynchronous context manager to change the
    :class:`contextvars.Context` for the current task.

    """
    task = _run.current_task()
    saved_context = task.context
    task.context = context

    try:
        await _run.cancel_shielded_checkpoint()
        yield
    finally:
        task.context = saved_context
        await _run.cancel_shielded_checkpoint()
