import errno
import logging
import os

import trio

__all__ = ["serve_listeners"]

# Errors that accept(2) can return, and which indicate that the system is
# overloaded
ACCEPT_CAPACITY_ERRNOS = {
    errno.EMFILE,
    errno.ENFILE,
    errno.ENOMEM,
    errno.ENOBUFS,
}

# How long to sleep when we get one of those errors
SLEEP_TIME = 0.100

# The logger we use to complain when this happens
LOGGER = logging.getLogger("trio.serve_listeners")


async def _run_handler(stream, handler):
    try:
        await handler(stream)
    finally:
        await trio.aclose_forcefully(stream)


async def _serve_one_listener(listener, connection_nursery, handler):
    async with listener:
        while True:
            try:
                stream = await listener.accept()
            except OSError as exc:
                if exc.errno in ACCEPT_CAPACITY_ERRNOS:
                    LOGGER.error(
                        "accept returned %s (%s); retrying in %s seconds",
                        errno.errorcode[exc.errno],
                        os.strerror(exc.errno),
                        SLEEP_TIME,
                        exc_info=True
                    )
                    await trio.sleep(SLEEP_TIME)
                else:
                    raise
            else:
                connection_nursery.start_soon(_run_handler, stream, handler)


async def serve_listeners(
    handler,
    listeners,
    *,
    connection_nursery=None,
    task_status=trio.STATUS_IGNORED
):
    async with trio.open_nursery() as nursery:
        if connection_nursery is None:
            connection_nursery = nursery
        for listener in listeners:
            nursery.start_soon(
                _serve_one_listener, listener, connection_nursery, handler
            )
        # The listeners are already queueing connections when we're called,
        # but we wait until the end to call started() just in case we get an
        # error or whatever.
        task_status.started(listeners)
