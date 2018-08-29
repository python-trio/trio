import sys

import os
import pytest
import signal

from ... import _core
from ..._subprocess.linux_waitpid import waitpid

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="linux waitpid only works on linux"
)


async def test_waitpid():
    pid = os.spawnvp(os.P_NOWAIT, "/bin/false", ("false",))
    result = await waitpid(pid)
    # exit code is a 16-bit int: (code, signal)
    assert result == (pid, 256)

    pid2 = os.spawnvp(os.P_NOWAIT, "/bin/true", ("true",))
    result = await waitpid(pid2)
    assert result == (pid2, 0)

    pid3 = os.spawnvp(os.P_NOWAIT, "/bin/sleep", ("/bin/sleep", "5"))
    os.kill(pid3, signal.SIGKILL)
    result = await waitpid(pid3)
    assert result == (pid3, 9)


async def test_waitpid_multiple_accesses():
    pid = os.spawnvp(os.P_NOWAIT, "/bin/sleep", ("/bin/sleep", "5"))

    async def waiter():
        result = await waitpid(pid)
        assert result == (pid, 9)

    async with _core.open_nursery() as n:
        n.start_soon(waiter)
        n.start_soon(waiter)

        os.kill(pid, signal.SIGKILL)


async def test_waitpid_no_process():
    with pytest.raises(ChildProcessError):
        # this PID probably doesn't exist
        await waitpid(100000)
