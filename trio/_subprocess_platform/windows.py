import subprocess
from .._wait_for_object import WaitForSingleObject


async def wait_child_exiting(process: subprocess.Popen) -> None:
    await WaitForSingleObject(int(process._handle))
