import _core
from ._core._windows_cffi import kernel32, raise_winerror
from ._wait_for_object import WaitForSingleObject

async def wait_child_exiting(pid):
    SYNCHRONIZE = 0x00100000  # dwDesiredAccess value
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        await _core.checkpoint()
        raise_winerror()
    try:
        await WaitForSingleObject(handle)
    finally:
        kernel32.CloseHandle(handle)
