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
    assert result[0] == pid
    assert os.WIFEXITED(result[1]) and os.WEXITSTATUS(result[1]) == 1

    pid2 = os.spawnvp(os.P_NOWAIT, "/bin/true", ("true",))
    result = await waitpid(pid2)
    assert result[0] == pid2
    assert os.WIFEXITED(result[1]) and os.WEXITSTATUS(result[1]) == 0

    pid3 = os.spawnvp(os.P_NOWAIT, "/bin/sleep", ("/bin/sleep", "5"))
    os.kill(pid3, signal.SIGKILL)
    result = await waitpid(pid3)
    assert result[0] == pid3
    status = os.WTERMSIG(result[1])
    assert os.WIFSIGNALED(result[1]) and status == 9


async def test_waitpid_no_process():
    with pytest.raises(ChildProcessError):
        # this PID does exist, but it's ourselves
        # which doesn't work
        await waitpid(os.getpid())
