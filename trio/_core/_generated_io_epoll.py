# ***********************************************************
# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******
# *************************************************************
from __future__ import annotations

from typing import TYPE_CHECKING

from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED
from ._run import GLOBAL_RUN_CONTEXT

if TYPE_CHECKING:
    from .._file_io import _HasFileNo
import sys

assert not TYPE_CHECKING or sys.platform == "linux"


async def wait_readable(fd: (int | _HasFileNo)) -> None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_readable(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


async def wait_writable(fd: (int | _HasFileNo)) -> None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_writable(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


def notify_closing(fd: (int | _HasFileNo)) -> None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.notify_closing(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context") from None
