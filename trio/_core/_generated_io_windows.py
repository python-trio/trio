# ***********************************************************
# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******
# *************************************************************
import select
import socket
import sys
from typing import (
    Awaitable,
    Callable,
    ContextManager,
    Iterator,
    Optional,
    Tuple,
    TYPE_CHECKING,
    Union,
)

from .._abc import Clock
from .._typing import _HasFileno
from .._core._entry_queue import TrioToken
from .. import _core
from ._run import GLOBAL_RUN_CONTEXT, _NO_SEND, _RunStatistics, Task
from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED
from ._instrumentation import Instrument

if TYPE_CHECKING and sys.platform == "win32":
    from ._io_windows import CompletionKeyEventInfo

# fmt: off


assert not TYPE_CHECKING or sys.platform == 'win32'


async def wait_readable(sock: int) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_readable(sock)
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def wait_writable(sock: int) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_writable(sock)
    except AttributeError:
        raise RuntimeError("must be called from async context")


def notify_closing(handle: int) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.notify_closing(handle)
    except AttributeError:
        raise RuntimeError("must be called from async context")


def register_with_iocp(handle: int) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.register_with_iocp(handle)
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def wait_overlapped(handle: socket.socket, lpOverlapped: Union[int,
    object]) ->object:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_overlapped(handle, lpOverlapped)
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def write_overlapped(handle: int, data: bytes, file_offset: int=0) ->int:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.write_overlapped(handle, data, file_offset)
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def readinto_overlapped(handle: int, buffer: bytearray, file_offset:
    int=0) ->int:
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


def monitor_completion_key() ->ContextManager[Tuple[int,
    '_core.UnboundedQueue[CompletionKeyEventInfo]']]:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.monitor_completion_key()
    except AttributeError:
        raise RuntimeError("must be called from async context")


# fmt: on
