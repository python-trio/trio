import math
import os
import random
import signal
import sys
import pytest

from .. import _core, move_on_after, sleep_forever, subprocess
from .._core.tests.tutil import slow
from ..testing import wait_all_tasks_blocked

posix = os.name == "posix"
if posix:
    from signal import SIGKILL, SIGTERM, SIGINT
else:
    SIGKILL, SIGTERM, SIGINT = None, None, None


def cmd_switch(posix_option, windows_pycode):
    return posix_option if posix else [
        sys.executable, "-c", "import sys; " + windows_pycode
    ]


EXIT_TRUE = cmd_switch(["true"], "sys.exit(0)")
EXIT_FALSE = cmd_switch(["false"], "sys.exit(1)")
CAT = cmd_switch(["cat"], "sys.stdout.buffer.write(sys.stdin.buffer.read())")


def SLEEP(seconds):
    return cmd_switch(
        ["sleep", str(seconds)], "import time; time.sleep({})".format(seconds)
    )


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
            await trio.sleep_forever()
    assert scope.cancelled_caught
    assert got_signal(proc, SIGKILL)


COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR = [
    sys.executable, "-c", "import sys\n"
    "data = sys.stdin.buffer.read()\n"
    "sys.stdout.buffer.write(data)\n"
    "sys.stderr.buffer.write(data[::-1])"
]


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


async def test_run():
    data = bytes(random.randint(0, 255) for _ in range(2**18))

    result = await subprocess.run(CAT, input=data, stdout=subprocess.PIPE)
    assert result.args == CAT
    assert result.returncode == 0
    assert result.stdout == data
    assert result.stderr is None

    result = await subprocess.run(
        CAT, stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    assert result.args == CAT
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr is None

    result = await subprocess.run(
        COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR,
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.args == COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR
    assert result.returncode == 0
    assert result.stdout == data
    assert result.stderr == data[::-1]

    with pytest.raises(ValueError):
        # can't use both input and stdin
        await subprocess.run(CAT, input=b"la di dah", stdin=subprocess.PIPE)

    with pytest.raises(ValueError):
        # can't use both timeout and deadline
        await subprocess.run(
            EXIT_TRUE, timeout=1, deadline=_core.current_time()
        )


@slow
async def test_run_timeout():
    data = b"1" * 65536 + b"2" * 65536 + b"3" * 65536
    child_script = """
import sys, time
sys.stdout.buffer.write(sys.stdin.buffer.read(32768))
time.sleep(10)
sys.stdout.buffer.write(sys.stdin.buffer.read())
"""

    for make_timeout_arg in (
        lambda: {"timeout": 1.0},
        lambda: {"deadline": _core.current_time() + 1.0}
    ):
        with pytest.raises(subprocess.TimeoutExpired) as excinfo:
            await subprocess.run(
                [sys.executable, "-c", child_script],
                input=data,
                stdout=subprocess.PIPE,
                **make_timeout_arg()
            )
        assert excinfo.value.cmd == [sys.executable, "-c", child_script]
        if "timeout" in make_timeout_arg():
            assert excinfo.value.timeout == 1.0
        else:
            assert 0.9 < excinfo.value.timeout < 1.1
        assert excinfo.value.stdout == data[:32768]
        assert excinfo.value.stderr is None


async def test_run_check():
    cmd = cmd_switch(
        "echo test >&2; false",
        "sys.stderr.buffer.write(b'test\\n'); sys.exit(1)",
    )

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        await subprocess.run(
            cmd,
            shell=posix,
            stderr=subprocess.PIPE,
            check=True,
        )
    assert excinfo.value.cmd == cmd
    assert excinfo.value.returncode == 1
    assert excinfo.value.stderr == b"test\n"
    assert excinfo.value.stdout is None


async def test_run_with_broken_pipe():
    result = await subprocess.run(
        [sys.executable, "-c", "import sys; sys.stdin.close()"],
        input=b"x" * 131072,
        stdout=subprocess.PIPE,
    )
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr is None


async def test_stderr_stdout():
    async with subprocess.Process(
        COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ) as proc:
        assert proc.stdout is not None
        assert proc.stderr is None

    result = await subprocess.run(
        COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR,
        input=b"1234",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert result.returncode == 0
    assert result.stdout == b"12344321"
    assert result.stderr is None

    # this one hits the branch where stderr=STDOUT but stdout
    # is not redirected
    result = await subprocess.run(CAT, input=b"", stderr=subprocess.STDOUT)
    assert result.returncode == 0
    assert result.stdout is None
    assert result.stderr is None

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
    with pytest.raises(NotImplementedError):
        subprocess.Process(["ls"], universal_newlines=True)
    with pytest.raises(ValueError):
        subprocess.Process(["ls"], bufsize=4096)


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
