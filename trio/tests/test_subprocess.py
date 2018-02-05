import os
import sys
import time
import subprocess

import pytest

from trio import _core

from trio._core import _fd_stream

timers = (-0.1,-0.01,-0.001, 0, 0.001, 0.01, 0.1)

@pytest.fixture(params=timers)
def timer(request):
    yield request.param

# TODO: there's more to life than Unix
def fork_sleep(timer=0):
    pid = os.spawnlp(os.P_NOWAIT, "sleep", "sleep", str(timer) if timer > 0 else "0")
    if timer < 0:
        time.sleep(-timer)
    return pid

def fork_error():
    pid = os.spawnlp(os.P_NOWAIT, "false", "false")
    return pid

async def test_wait_delayed(timer):
    pid = fork_sleep(timer)
    res = await _core.wait_for_child(pid)
    assert res == 0
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)

async def test_wait_error():
    pid = fork_error()
    res = await _core.wait_for_child(pid)
    assert res == 1
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)

