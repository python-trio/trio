import os
import signal
import subprocess
import sys
import pytest
import random
from functools import partial

from .. import (
    _core,
    move_on_after,
    fail_after,
    sleep,
    sleep_forever,
    Process,
    open_process,
    run_process,
    TrioDeprecationWarning,
)
from .._core.tests.tutil import slow, skip_if_fbsd_pipes_broken
from ..testing import wait_all_tasks_blocked

posix = os.name == "posix"
if posix:
    from signal import SIGKILL, SIGTERM, SIGUSR1
else:
    SIGKILL, SIGTERM, SIGUSR1 = None, None, None


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
    async with await open_process(EXIT_TRUE) as proc:
        pass
    assert isinstance(proc, Process)
    assert proc._pidfd is None
    assert proc.returncode == 0
    assert repr(proc) == f"<trio.Process {EXIT_TRUE}: exited with status 0>"

    async with await open_process(EXIT_FALSE) as proc:
        pass
    assert proc.returncode == 1
    assert repr(proc) == "<trio.Process {!r}: {}>".format(
        EXIT_FALSE, "exited with status 1"
    )


async def test_auto_update_returncode():
    p = await open_process(SLEEP(9999))
    assert p.returncode is None
    assert "running" in repr(p)
    p.kill()
    p._proc.wait()
    assert p.returncode is not None
    assert "exited" in repr(p)
    assert p._pidfd is None
    assert p.returncode is not None


async def test_multi_wait():
    async with await open_process(SLEEP(10)) as proc:
        # Check that wait (including multi-wait) tolerates being cancelled
        async with _core.open_nursery() as nursery:
            nursery.start_soon(proc.wait)
            nursery.start_soon(proc.wait)
            nursery.start_soon(proc.wait)
            await wait_all_tasks_blocked()
            nursery.cancel_scope.cancel()

        # Now try waiting for real
        async with _core.open_nursery() as nursery:
            nursery.start_soon(proc.wait)
            nursery.start_soon(proc.wait)
            nursery.start_soon(proc.wait)
            await wait_all_tasks_blocked()
            proc.kill()


async def test_kill_when_context_cancelled():
    with move_on_after(100) as scope:
        async with await open_process(SLEEP(10)) as proc:
            assert proc.poll() is None
            scope.cancel()
            await sleep_forever()
    assert scope.cancelled_caught
    assert got_signal(proc, SIGKILL)
    assert repr(proc) == "<trio.Process {!r}: {}>".format(
        SLEEP(10), "exited with signal 9" if posix else "exited with status 1"
    )


COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR = python(
    "data = sys.stdin.buffer.read(); "
    "sys.stdout.buffer.write(data); "
    "sys.stderr.buffer.write(data[::-1])"
)


async def test_pipes():
    async with await open_process(
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
            async for chunk in stream:
                seen += chunk
            assert seen == expected

        async with _core.open_nursery() as nursery:
            # fail eventually if something is broken
            nursery.cancel_scope.deadline = _core.current_time() + 30.0
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

    async with await open_process(
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
                nursery.start_soon(drain_one, proc.stderr, request * 2, idx * 2 + 1)

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


async def test_run():
    data = bytes(random.randint(0, 255) for _ in range(2 ** 18))

    result = await run_process(
        CAT, stdin=data, capture_stdout=True, capture_stderr=True
    )
    assert result.args == CAT
    assert result.returncode == 0
    assert result.stdout == data
    assert result.stderr == b""

    result = await run_process(CAT, capture_stdout=True)
    assert result.args == CAT
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr is None

    result = await run_process(
        COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR,
        stdin=data,
        capture_stdout=True,
        capture_stderr=True,
    )
    assert result.args == COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR
    assert result.returncode == 0
    assert result.stdout == data
    assert result.stderr == data[::-1]

    # invalid combinations
    with pytest.raises(UnicodeError):
        await run_process(CAT, stdin="oh no, it's text")
    with pytest.raises(ValueError):
        await run_process(CAT, stdin=subprocess.PIPE)
    with pytest.raises(ValueError):
        await run_process(CAT, capture_stdout=True, stdout=subprocess.DEVNULL)
    with pytest.raises(ValueError):
        await run_process(CAT, capture_stderr=True, stderr=None)


async def test_run_check():
    cmd = python("sys.stderr.buffer.write(b'test\\n'); sys.exit(1)")
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        await run_process(cmd, stdin=subprocess.DEVNULL, capture_stderr=True)
    assert excinfo.value.cmd == cmd
    assert excinfo.value.returncode == 1
    assert excinfo.value.stderr == b"test\n"
    assert excinfo.value.stdout is None

    result = await run_process(
        cmd, capture_stdout=True, capture_stderr=True, check=False
    )
    assert result.args == cmd
    assert result.stdout == b""
    assert result.stderr == b"test\n"
    assert result.returncode == 1


@skip_if_fbsd_pipes_broken
async def test_run_with_broken_pipe():
    result = await run_process(
        [sys.executable, "-c", "import sys; sys.stdin.close()"], stdin=b"x" * 131072
    )
    assert result.returncode == 0
    assert result.stdout is result.stderr is None


async def test_stderr_stdout():
    async with await open_process(
        COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ) as proc:
        assert proc.stdout is not None
        assert proc.stderr is None
        await proc.stdio.send_all(b"1234")
        await proc.stdio.send_eof()

        output = []
        while True:
            chunk = await proc.stdio.receive_some(16)
            if chunk == b"":
                break
            output.append(chunk)
        assert b"".join(output) == b"12344321"
    assert proc.returncode == 0

    # equivalent test with run_process()
    result = await run_process(
        COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR,
        stdin=b"1234",
        capture_stdout=True,
        stderr=subprocess.STDOUT,
    )
    assert result.returncode == 0
    assert result.stdout == b"12344321"
    assert result.stderr is None

    # this one hits the branch where stderr=STDOUT but stdout
    # is not redirected
    async with await open_process(
        CAT, stdin=subprocess.PIPE, stderr=subprocess.STDOUT
    ) as proc:
        assert proc.stdout is None
        assert proc.stderr is None
        await proc.stdin.aclose()
    assert proc.returncode == 0

    if posix:
        try:
            r, w = os.pipe()

            async with await open_process(
                COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR,
                stdin=subprocess.PIPE,
                stdout=w,
                stderr=subprocess.STDOUT,
            ) as proc:
                os.close(w)
                assert proc.stdio is None
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
        await open_process(["ls"], encoding="utf-8")
    assert "unbuffered byte streams" in str(excinfo.value)
    assert "the 'encoding' option is not supported" in str(excinfo.value)

    if posix:
        with pytest.raises(TypeError) as excinfo:
            await open_process(["ls"], shell=True)
        with pytest.raises(TypeError) as excinfo:
            await open_process("ls", shell=False)


async def test_signals():
    async def test_one_signal(send_it, signum):
        with move_on_after(1.0) as scope:
            async with await open_process(SLEEP(3600)) as proc:
                send_it(proc)
        assert not scope.cancelled_caught
        if posix:
            assert proc.returncode == -signum
        else:
            assert proc.returncode != 0

    await test_one_signal(Process.kill, SIGKILL)
    await test_one_signal(Process.terminate, SIGTERM)
    # Test that we can send arbitrary signals.
    #
    # We used to use SIGINT here, but it turns out that the Python interpreter
    # has race conditions that can cause it to explode in weird ways if it
    # tries to handle SIGINT during startup. SIGUSR1's default disposition is
    # to terminate the target process, and Python doesn't try to do anything
    # clever to handle it.
    if posix:
        await test_one_signal(lambda proc: proc.send_signal(SIGUSR1), SIGUSR1)


@pytest.mark.skipif(not posix, reason="POSIX specific")
async def test_wait_reapable_fails():
    old_sigchld = signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    try:
        # With SIGCHLD disabled, the wait() syscall will wait for the
        # process to exit but then fail with ECHILD. Make sure we
        # support this case as the stdlib subprocess module does.
        async with await open_process(SLEEP(3600)) as proc:
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

    got_alarm = False
    sleeper = subprocess.Popen(["sleep", "3600"])

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


async def test_custom_deliver_cancel():
    custom_deliver_cancel_called = False

    async def custom_deliver_cancel(proc):
        nonlocal custom_deliver_cancel_called
        custom_deliver_cancel_called = True
        proc.terminate()
        # Make sure this does get cancelled when the process exits, and that
        # the process really exited.
        try:
            await sleep_forever()
        finally:
            assert proc.returncode is not None

    async with _core.open_nursery() as nursery:
        nursery.start_soon(
            partial(run_process, SLEEP(9999), deliver_cancel=custom_deliver_cancel)
        )
        await wait_all_tasks_blocked()
        nursery.cancel_scope.cancel()

    assert custom_deliver_cancel_called


async def test_warn_on_failed_cancel_terminate(monkeypatch):
    original_terminate = Process.terminate

    def broken_terminate(self):
        original_terminate(self)
        raise OSError("whoops")

    monkeypatch.setattr(Process, "terminate", broken_terminate)

    with pytest.warns(RuntimeWarning, match=".*whoops.*"):
        async with _core.open_nursery() as nursery:
            nursery.start_soon(run_process, SLEEP(9999))
            await wait_all_tasks_blocked()
            nursery.cancel_scope.cancel()


@pytest.mark.skipif(os.name != "posix", reason="posix only")
async def test_warn_on_cancel_SIGKILL_escalation(autojump_clock, monkeypatch):
    monkeypatch.setattr(Process, "terminate", lambda *args: None)

    with pytest.warns(RuntimeWarning, match=".*ignored SIGTERM.*"):
        async with _core.open_nursery() as nursery:
            nursery.start_soon(run_process, SLEEP(9999))
            await wait_all_tasks_blocked()
            nursery.cancel_scope.cancel()
