import math
import os
import random
import signal
import sys
import pytest

from .. import (
    _core, move_on_after, fail_after, sleep, sleep_forever, subprocess
)
from .._core.tests.tutil import slow
from ..testing import wait_all_tasks_blocked

posix = os.name == "posix"
if posix:
    from signal import SIGKILL, SIGTERM, SIGINT
else:
    SIGKILL, SIGTERM, SIGINT = None, None, None


# Since Windows has very few command-line utilities generally available,
# all of our subprocesses are Python processes running short bits of
# (mostly) cross-platform code.
def python(code):
    return [sys.executable, "-u", "-c", "import sys; " + code]


EXIT_TRUE = python("sys.exit(0)")
EXIT_FALSE = python("sys.exit(1)")
CAT = python("sys.stdout.buffer.write(sys.stdin.buffer.read())")
SLEEP = lambda seconds: python("import time; time.sleep({})".format(seconds))


def got_signal(proc, sig):
    if posix:
        return proc.returncode == -sig
    else:
        return proc.returncode != 0


async def test_basic():
    async with subprocess.Process(EXIT_TRUE) as proc:
        assert proc.returncode is None
    assert proc.returncode == 0


async def test_kill_when_context_cancelled():
    with move_on_after(0) as scope:
        async with subprocess.Process(SLEEP(10)) as proc:
            assert proc.poll() is None
            # Process context entry is synchronous, so this is the
            # only checkpoint:
            await sleep_forever()
    assert scope.cancelled_caught
    assert got_signal(proc, SIGKILL)


COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR = python(
    "data = sys.stdin.buffer.read(); "
    "sys.stdout.buffer.write(data); "
    "sys.stderr.buffer.write(data[::-1])"
)


async def test_pipes():
    async with subprocess.Process(
        COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as proc:
        msg = b"the quick brown fox jumps over the lazy dog"

        async def feed_input():
            await proc.stdin.send_all(msg)
            await proc.stdin.aclose()

        async def check_output(stream, expected):
            seen = bytearray()
            while True:
                chunk = await stream.receive_some(4096)
                if not chunk:
                    break
                seen.extend(chunk)
            assert seen == expected

        async with _core.open_nursery() as nursery:
            # fail quickly if something is broken
            nursery.cancel_scope.deadline = _core.current_time() + 3.0
            nursery.start_soon(feed_input)
            nursery.start_soon(check_output, proc.stdout, msg)
            nursery.start_soon(check_output, proc.stderr, msg[::-1])

        assert not nursery.cancel_scope.cancelled_caught
        assert 0 == await proc.wait()


async def test_interactive():
    # Test some back-and-forth with a subprocess. This one works like so:
    # in: 32\n
    # out: 0000...0000\n (32 zeroes)
    # err: 1111...1111\n (64 ones)
    # in: 10\n
    # out: 2222222222\n (10 twos)
    # err: 3333....3333\n (20 threes)
    # in: EOF
    # out: EOF
    # err: EOF

    async with subprocess.Process(
        python(
            "idx = 0\n"
            "while True:\n"
            "    line = sys.stdin.readline()\n"
            "    if line == '': break\n"
            "    request = int(line.strip())\n"
            "    print(str(idx * 2) * request)\n"
            "    print(str(idx * 2 + 1) * request * 2, file=sys.stderr)\n"
            "    idx += 1\n"
        ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as proc:

        newline = b"\n" if posix else b"\r\n"

        async def expect(idx, request):
            async with _core.open_nursery() as nursery:

                async def drain_one(stream, count, digit):
                    while count > 0:
                        result = await stream.receive_some(count)
                        assert result == (
                            "{}".format(digit).encode("utf-8") * len(result)
                        )
                        count -= len(result)
                    assert count == 0
                    assert await stream.receive_some(len(newline)) == newline

                nursery.start_soon(drain_one, proc.stdout, request, idx * 2)
                nursery.start_soon(
                    drain_one, proc.stderr, request * 2, idx * 2 + 1
                )

        with fail_after(5):
            await proc.stdin.send_all(b"12")
            await sleep(0.1)
            await proc.stdin.send_all(b"345" + newline)
            await expect(0, 12345)
            await proc.stdin.send_all(b"100" + newline + b"200" + newline)
            await expect(1, 100)
            await expect(2, 200)
            await proc.stdin.send_all(b"0" + newline)
            await expect(3, 0)
            await proc.stdin.send_all(b"999999")
            with move_on_after(0.1) as scope:
                await expect(4, 0)
            assert scope.cancelled_caught
            await proc.stdin.send_all(newline)
            await expect(4, 999999)
            await proc.stdin.aclose()
            assert await proc.stdout.receive_some(1) == b""
            assert await proc.stderr.receive_some(1) == b""
    assert proc.returncode == 0


async def test_stderr_stdout():
    async with subprocess.Process(
        COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ) as proc:
        assert proc.stdout is not None
        assert proc.stderr is None
        await proc.stdin.send_all(b"1234")
        await proc.stdin.aclose()

        output = []
        while True:
            chunk = await proc.stdout.receive_some(16)
            if chunk == b"":
                break
            output.append(chunk)
        assert b"".join(output) == b"12344321"
    assert proc.returncode == 0

    # this one hits the branch where stderr=STDOUT but stdout
    # is not redirected
    async with subprocess.Process(
        CAT, stdin=subprocess.PIPE, stderr=subprocess.STDOUT
    ) as proc:
        assert proc.stdout is None
        assert proc.stderr is None
        await proc.stdin.aclose()
    assert proc.returncode == 0

    if posix:
        try:
            r, w = os.pipe()

            async with subprocess.Process(
                COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR,
                stdin=subprocess.PIPE,
                stdout=w,
                stderr=subprocess.STDOUT,
            ) as proc:
                os.close(w)
                assert proc.stdout is None
                assert proc.stderr is None
                await proc.stdin.send_all(b"1234")
                await proc.stdin.aclose()
                assert await proc.wait() == 0
                assert os.read(r, 4096) == b"12344321"
                assert os.read(r, 4096) == b""
        finally:
            os.close(r)


async def test_errors():
    with pytest.raises(TypeError) as excinfo:
        subprocess.Process(["ls"], encoding="utf-8")
    assert "unbuffered byte streams" in str(excinfo.value)
    assert "the 'encoding' option is not supported" in str(excinfo.value)


async def test_signals():
    async def test_one_signal(send_it, signum):
        with move_on_after(1.0) as scope:
            async with subprocess.Process(SLEEP(3600)) as proc:
                send_it(proc)
        assert not scope.cancelled_caught
        if posix:
            assert proc.returncode == -signum
        else:
            assert proc.returncode != 0

    await test_one_signal(subprocess.Process.kill, SIGKILL)
    await test_one_signal(subprocess.Process.terminate, SIGTERM)
    if posix:
        await test_one_signal(lambda proc: proc.send_signal(SIGINT), SIGINT)


@pytest.mark.skipif(not posix, reason="POSIX specific")
async def test_wait_reapable_fails():
    old_sigchld = signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    try:
        # With SIGCHLD disabled, the wait() syscall will wait for the
        # process to exit but then fail with ECHILD. Make sure we
        # support this case as the stdlib subprocess module does.
        async with subprocess.Process(SLEEP(3600)) as proc:
            async with _core.open_nursery() as nursery:
                nursery.start_soon(proc.wait)
                await wait_all_tasks_blocked()
                proc.kill()
                nursery.cancel_scope.deadline = _core.current_time() + 1.0
            assert not nursery.cancel_scope.cancelled_caught
            assert proc.returncode == 0  # exit status unknowable, so...
    finally:
        signal.signal(signal.SIGCHLD, old_sigchld)


@slow
def test_waitid_eintr():
    # This only matters on PyPy (where we're coding EINTR handling
    # ourselves) but the test works on all waitid platforms.
    from .._subprocess_platform import wait_child_exiting
    if not wait_child_exiting.__module__.endswith("waitid"):
        pytest.skip("waitid only")
    from .._subprocess_platform.waitid import sync_wait_reapable
    import subprocess as stdlib_subprocess

    got_alarm = False
    sleeper = stdlib_subprocess.Popen(["sleep", "3600"])

    def on_alarm(sig, frame):
        nonlocal got_alarm
        got_alarm = True
        sleeper.kill()

    old_sigalrm = signal.signal(signal.SIGALRM, on_alarm)
    try:
        signal.alarm(1)
        sync_wait_reapable(sleeper.pid)
        assert sleeper.wait(timeout=1) == -9
    finally:
        if sleeper.returncode is None:  # pragma: no cover
            # We only get here if something fails in the above;
            # if the test passes, wait() will reap the process
            sleeper.kill()
            sleeper.wait()
        signal.signal(signal.SIGALRM, old_sigalrm)


def test_all_constants_reexported():
    trio_subprocess_exports = set(dir(subprocess))
    import subprocess as stdlib_subprocess

    for name in dir(stdlib_subprocess):
        if name.isupper() and name[0] != "_":
            stdlib_constant = name
            assert stdlib_constant in trio_subprocess_exports
