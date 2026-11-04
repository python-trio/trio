import os
import sys
from collections.abc import Sequence
from typing import TypeAlias

import trio
from typing_extensions import assert_type

StrOrBytesPath: TypeAlias = str | bytes | os.PathLike[str] | os.PathLike[bytes]


async def test() -> None:
    # this could test more by using platform checks, but currently this
    # is just regression tests + sanity checks.
    await trio.run_process("python", executable="ls")
    await trio.lowlevel.open_process("python", executable="ls")

    # note: there's no error code on the type ignore as it varies
    # between platforms.
    await trio.run_process("python", capture_stdout=True)
    await trio.lowlevel.open_process("python", capture_stdout=True)  # type: ignore

    if sys.platform != "win32" and sys.version_info >= (3, 9):
        await trio.run_process("python", extra_groups=[5])
        await trio.lowlevel.open_process("python", extra_groups=[5])

        # 3.11+:
        await trio.run_process("python", process_group=5)  # type: ignore
        await trio.lowlevel.open_process("python", process_group=5)  # type: ignore


def check_processes(proc: trio.Process) -> None:
    assert_type(proc.stdin, trio.abc.SendStream | None)
    assert_type(proc.stdout, trio.abc.ReceiveStream | None)
    assert_type(proc.stderr, trio.abc.ReceiveStream | None)
    assert_type(
        proc.stdio,
        trio.StapledStream[trio.abc.SendStream, trio.abc.ReceiveStream] | None,
    )
    assert_type(proc.args, StrOrBytesPath | Sequence[StrOrBytesPath])
    assert_type(proc.pid, int)
