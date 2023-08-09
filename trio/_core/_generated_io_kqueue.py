# ***********************************************************
# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******
# *************************************************************
# isort: skip_file
from __future__ import annotations

from collections.abc import Callable, Awaitable
from typing import Any

from outcome import Outcome
import contextvars

from ._instrumentation import Instrument
from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED
from ._run import _NO_SEND, GLOBAL_RUN_CONTEXT
import trio

# fmt: off


def current_kqueue():
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.current_kqueue()
    except AttributeError:
        raise RuntimeError("must be called from async context")


def monitor_kevent(ident, filter):
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.monitor_kevent(ident, filter)
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def wait_kevent(ident, filter, abort_func):
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_kevent(ident, filter, abort_func)
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def wait_readable(fd):
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_readable(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def wait_writable(fd):
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_writable(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context")


def notify_closing(fd):
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.notify_closing(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context")


# fmt: on
