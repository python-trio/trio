import os
import sys
import time
import subprocess

import pytest

from trio import _core
subproc = _core.run_subprocess

from trio._core import _fd_stream

timers = (-0.1, -0.01, -0.001, 0, 0.001, 0.01, 0.1)


@pytest.fixture(params=timers)
def timer(request):
    yield request.param


# TODO: there's more to life than Unix
def fork_sleep(timer=0):
    pid = os.spawnlp(
        os.P_NOWAIT, "sleep", "sleep",
        str(timer) if timer > 0 else "0"
    )
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


async def test_basics():
    fd = os.open(os.devnull, os.O_RDONLY)
    os.close(fd)
    async with subproc(
        sys.executable,
        "-c",
        "import sys; sys.exit(0)",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    ) as p:
        assert isinstance(p.stdin, _fd_stream.WriteFDStream)
        assert isinstance(p.stdout, _fd_stream.ReadFDStream)
        assert isinstance(p.stderr, _fd_stream.ReadFDStream)
    assert p.returncode == 0
    fd2 = os.open(os.devnull, os.O_RDONLY)
    os.close(fd2)
    assert fd == fd2  # no file descriptor leaks please


async def test_exitcode():
    # call() function with sequence argument
    async with subproc(sys.executable, "-c", "import sys; sys.exit(47)") as p:
        assert p.stdin is None
        assert p.stdout is None
        assert p.stderr is None
    assert p.returncode == 47


async def test_talking():
    async with subproc(
        sys.executable,
        "-c",
        r"import sys; assert sys.stdin.read(4) == 'foo\n'; sys.stdout.write('bar\n'); sys.stderr.write('baz\n'); sys.exit(0)",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    ) as p:
        await p.stdin.send_all(b"foo\n")
        assert await p.stdout.receive_some(42) == b"bar\n"
        assert await p.stderr.receive_some(42) == b"baz\n"
    assert p.returncode == 0
