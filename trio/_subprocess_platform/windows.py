import subprocess
from .._wait_for_object import WaitForSingleObject


async def wait_child_exiting(process: subprocess.Popen) -> None:
    if process.returncode is not None:
        return
    await WaitForSingleObject(int(process._handle))
