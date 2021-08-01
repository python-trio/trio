from contextvars import Context

from async_generator import asynccontextmanager

from . import _run


@asynccontextmanager
async def change_context(context):
    """Asynchronous context manager to change the :class:`contextvars.Context`
    for the current task.

    """
    task = _run.current_task()
    saved_context = task.context
    task.context = context

    try:
        await _run.checkpoint()
        yield
    finally:
        task.context = saved_context
        # I assume this is right?
        await _run.cancel_shielded_checkpoint()

