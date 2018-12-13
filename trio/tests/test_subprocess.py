import math
import os
import random
import signal
import sys
import pytest

from .. import _core, move_on_after, sleep, subprocess
from ..testing import wait_all_tasks_blocked

posix = os.name == "posix"

pytestmark = pytest.mark.skipif(not posix, reason="no windows support yet")


async def test_basic():
    async with subprocess.Process(["true"]) as proc:
        assert proc.returncode is None
    assert proc.returncode == 0


async def test_kill_when_context_cancelled():
    with _core.open_cancel_scope() as scope:
        async with subprocess.Process(["sleep", "10"]) as proc:
            while True:
                await sleep(0.01)
                assert proc.poll() is None

                # Don't set the deadline until we've done at least
                # one poll, to avoid coverage flapping if starting
                # the process takes a long time
                if scope.deadline == +math.inf:
                    scope.deadline = _core.current_time() + 0.2

    assert scope.cancelled_caught
    assert proc.returncode == -signal.SIGKILL


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

    result = await subprocess.run(["cat"], input=data, stdout=subprocess.PIPE)
    assert result.args == ["cat"]
    assert result.returncode == 0
    assert result.stdout == data
    assert result.stderr is None

    result = await subprocess.run(
        ["cat"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    assert result.args == ["cat"]
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
        await subprocess.run(
            ["cat"], input=b"la di dah", stdin=subprocess.PIPE
        )

    with pytest.raises(ValueError):
        # can't use both timeout and deadline
        await subprocess.run(
            ["true"], timeout=1, deadline=_core.current_time()
        )


async def test_run_timeout():
    data = b"1" * 65536 + b"2" * 65536 + b"3" * 65536
    child_script = """
import sys, time
sys.stdout.buffer.write(sys.stdin.buffer.read(32768))
time.sleep(10)
sys.stdout.buffer.write(sys.stdin.buffer.read())
"""

    for make_timeout_arg in (
        lambda: {"timeout": 0.25},
        lambda: {"deadline": _core.current_time() + 0.25}
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
            assert excinfo.value.timeout == 0.25
        else:
            assert 0.2 < excinfo.value.timeout < 0.3
        assert excinfo.value.stdout == data[:32768]
        assert excinfo.value.stderr is None


async def test_call_and_check():
    assert await subprocess.call(["true"]) == 0
    assert await subprocess.call(["false"]) == 1

    assert await subprocess.check_call(["true"]) == 0
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        await subprocess.check_call(["false"])
    assert excinfo.value.returncode == 1
    assert excinfo.value.cmd == ["false"]
    assert excinfo.value.output is None

    assert await subprocess.check_output(["echo", "hi"]) == b"hi\n"
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        await subprocess.check_output("echo lo; false", shell=True)
    assert excinfo.value.returncode == 1
    assert excinfo.value.cmd == "echo lo; false"
    assert excinfo.value.output == b"lo\n"

    with pytest.raises(ValueError):
        await subprocess.check_output(["true"], stdout=subprocess.DEVNULL)


async def test_run_check():
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        await subprocess.run(
            "echo test >&2; false",
            shell=True,
            stderr=subprocess.PIPE,
            check=True,
        )
    assert excinfo.value.cmd == "echo test >&2; false"
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
    result = await subprocess.run(["cat"], input=b"", stderr=subprocess.STDOUT)
    assert result.returncode == 0
    assert result.stdout is None
    assert result.stderr is None

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
            async with subprocess.Process(["sleep", "3600"]) as proc:
                send_it(proc)
        assert not scope.cancelled_caught
        assert proc.returncode == -signum

    await test_one_signal(subprocess.Process.kill, signal.SIGKILL)
    await test_one_signal(subprocess.Process.terminate, signal.SIGTERM)
    await test_one_signal(
        lambda proc: proc.send_signal(signal.SIGINT), signal.SIGINT
    )


async def test_wait_reapable_fails():
    old_sigchld = signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    try:
        # With SIGCHLD disabled, the wait() syscall will wait for the
        # process to exit but then fail with ECHILD. Process.wait()
        # has logic that suppresses wait() errors if the process has
        # in fact exited; this test tries to exercise that logic.
        async with subprocess.Process(["sleep", "3600"]) as proc:
            async with _core.open_nursery() as nursery:
                nursery.start_soon(proc.wait)
                await wait_all_tasks_blocked()
                proc.kill()
                nursery.cancel_scope.deadline = _core.current_time() + 1.0
            assert not nursery.cancel_scope.cancelled_caught
            assert proc.returncode == 0  # exit status unknowable, so...
    finally:
        signal.signal(signal.SIGCHLD, old_sigchld)
