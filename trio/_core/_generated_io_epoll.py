# ***********************************************************
# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******
# *************************************************************
# isort: skip
from __future__ import annotations

from typing import TYPE_CHECKING

from ._instrumentation import Instrument
from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED
from ._run import _NO_SEND, GLOBAL_RUN_CONTEXT

if TYPE_CHECKING:
    from socket import socket

# fmt: off


async def wait_readable(fd: (int | socket)) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_readable(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def wait_writable(fd: (int | socket)) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_writable(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context")


def notify_closing(fd: (int | socket)) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.notify_closing(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context")


# fmt: on
