from __future__ import annotations

import _winapi
import itertools
import os
import tempfile
from typing import TYPE_CHECKING

from .._wait_for_object import WaitForSingleObject

if TYPE_CHECKING:
    from .. import _subprocess

_pipe_counter = itertools.count()


def windows_pipe(
    *,
    duplex: bool = False,
    overlapped: tuple[bool, bool] = (True, True),
    bufsize: int = 8192,
) -> tuple[int, int]:
    """Like os.pipe() but with overlapped support and using handles not fds.

    Adapted from CPython's asyncio.windows_utils.pipe().
    Copyright (c) 2001-2026 Python Software Foundation; All Rights Reserved.
    Licensed under the Python Software Foundation License Version 2.

    Changes from CPython:
    - Renamed pipe prefix from r'\\.\\pipe\asyncio-pipe-*' to r'\\.\\pipe\trio-pipe-*'.
    - Modernized type hints for Trio's static typing and mypy checks.
    - Explicit exception guard ensures early handle is closed if connection fails.
    """
    address = tempfile.mktemp(
        prefix=rf"\\.\pipe\trio-pipe-{os.getpid():d}-{next(_pipe_counter):d}-"
    )

    if duplex:
        openmode = _winapi.PIPE_ACCESS_DUPLEX
        access = _winapi.GENERIC_READ | _winapi.GENERIC_WRITE
        obsize, ibsize = bufsize, bufsize
    else:
        openmode = _winapi.PIPE_ACCESS_INBOUND
        access = _winapi.GENERIC_WRITE
        obsize, ibsize = 0, bufsize

    openmode |= _winapi.FILE_FLAG_FIRST_PIPE_INSTANCE

    if overlapped[0]:
        openmode |= _winapi.FILE_FLAG_OVERLAPPED

    flags_and_attribs = _winapi.FILE_FLAG_OVERLAPPED if overlapped[1] else 0

    h1: int | None = None
    h2: int | None = None
    try:
        h1 = _winapi.CreateNamedPipe(
            address,
            openmode,
            _winapi.PIPE_WAIT,
            1,
            obsize,
            ibsize,
            _winapi.NMPWAIT_WAIT_FOREVER,
            _winapi.NULL,
        )

        h2 = _winapi.CreateFile(
            address,
            access,
            0,
            _winapi.NULL,
            _winapi.OPEN_EXISTING,
            flags_and_attribs,
            _winapi.NULL,
        )

        ov = _winapi.ConnectNamedPipe(h1, overlapped=True)
        ov.GetOverlappedResult(True)
        return h1, h2
    except:
        if h1 is not None:
            _winapi.CloseHandle(h1)
        if h2 is not None:
            _winapi.CloseHandle(h2)
        raise


async def wait_child_exiting(process: _subprocess.Process) -> None:
    # _handle is not in Popen stubs, though it is present on Windows.
    await WaitForSingleObject(int(process._proc._handle))  # type: ignore[attr-defined]
