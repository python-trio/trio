import sys

import os
import pytest
import signal

from .._core.tests.tutil import slow
from .._waitpid_linux import waitpid

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="linux waitpid only works on linux"
)


@slow
async def test_waitpid():
    pid = os.spawnvp(os.P_NOWAIT, "/bin/false", ("false",))
    result = await waitpid(pid)
    # exit code is a 16-bit int: (code, signal)
    assert result == (pid, 256)

    pid2 = os.spawnvp(os.P_NOWAIT, "/bin/sleep", ("/bin/sleep", "1"))
    result = await waitpid(pid2)
    assert result == (pid2, 0)

    pid3 = os.spawnvp(os.P_NOWAIT, "/bin/sleep", ("/bin/sleep", "5"))
    os.kill(pid3, signal.SIGKILL)
    result = await waitpid(pid3)
    assert result == (pid3, 9)
