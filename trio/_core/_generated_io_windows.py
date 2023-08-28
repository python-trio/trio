# ***********************************************************
# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******
# *************************************************************
from __future__ import annotations

import sys
from typing import TYPE_CHECKING, ContextManager

from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED
from ._run import GLOBAL_RUN_CONTEXT

if TYPE_CHECKING:
    from .._file_io import _HasFileNo
    from ._windows_cffi import Handle, CData
    from typing_extensions import Buffer

    from ._unbounded_queue import UnboundedQueue

assert not TYPE_CHECKING or sys.platform == "win32"


async def wait_readable(sock: (_HasFileNo | int)) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_readable(sock)
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def wait_writable(sock: (_HasFileNo | int)) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_writable(sock)
    except AttributeError:
        raise RuntimeError("must be called from async context")


def notify_closing(handle: (Handle | int | _HasFileNo)) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.notify_closing(handle)
    except AttributeError:
        raise RuntimeError("must be called from async context")


def register_with_iocp(handle: (int | CData)) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.register_with_iocp(handle)
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def wait_overlapped(handle_: (int | CData), lpOverlapped: (CData | int)
    ) ->object:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_overlapped(handle_, lpOverlapped)
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def write_overlapped(handle: (int | CData), data: Buffer, file_offset:
    int=0) ->int:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.write_overlapped(
            handle, data, file_offset
        )
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def readinto_overlapped(handle: (int | CData), buffer: Buffer,
    file_offset: int=0) ->int:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.readinto_overlapped(
            handle, buffer, file_offset
        )
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
