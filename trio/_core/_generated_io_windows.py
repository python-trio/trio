# ***********************************************************
# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******
# *************************************************************
# Don't lint this file, generation will not format this too nicely.
# isort: skip_file
# fmt: off
from __future__ import annotations

from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED
from ._run import GLOBAL_RUN_CONTEXT
from typing import TYPE_CHECKING, ContextManager

if TYPE_CHECKING:
    from ._unbounded_queue import UnboundedQueue
import sys

assert not TYPE_CHECKING or sys.platform=="win32"


async def wait_readable(sock) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_readable(sock)
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def wait_writable(sock) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_writable(sock)
    except AttributeError:
        raise RuntimeError("must be called from async context")


def notify_closing(handle) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.notify_closing(handle)
    except AttributeError:
        raise RuntimeError("must be called from async context")


def register_with_iocp(handle) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.register_with_iocp(handle)
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def wait_overlapped(handle, lpOverlapped):
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_overlapped(handle, lpOverlapped)
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def write_overlapped(handle, data, file_offset=0):
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.write_overlapped(handle, data, file_offset)
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def readinto_overlapped(handle, buffer, file_offset=0):
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.readinto_overlapped(handle, buffer, file_offset)
    except AttributeError:
        raise RuntimeError("must be called from async context")


def current_iocp() ->int:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.current_iocp()
    except AttributeError:
        raise RuntimeError("must be called from async context")


def monitor_completion_key() ->ContextManager[tuple[int, UnboundedQueue[object]]]:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.monitor_completion_key()
    except AttributeError:
        raise RuntimeError("must be called from async context")


# fmt: on
