import math
import json
import os
import random
import shlex
import signal
import subprocess as stdlib_subprocess
import sys
import tempfile
import pytest
from functools import partial

from .. import (
    _core,
    move_on_after,
    fail_after,
    sleep,
    sleep_forever,
    Process,
    ProcessStream,
    subprocess,
    open_process,
    run_process,
    delegate_to_process,
)
from .._core.tests.tutil import slow
from ..testing import wait_all_tasks_blocked, assert_checkpoints

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
YES = python("\n" "while True:\n" "    sys.stdout.buffer.write('y\\n')\n")
SLEEP = lambda seconds: python("import time; time.sleep({})".format(seconds))


def got_signal(proc, sig):
    if posix:
        return proc.returncode == -sig
    else:
        return proc.returncode != 0


async def test_basic():
    repr_template = "<trio.Process {!r}: {{}}>".format(EXIT_TRUE)
    async with Process(EXIT_TRUE) as proc:
        assert proc.returncode is None
        assert proc.failed is None
        assert repr(proc) == repr_template.format(
            "running with PID {}".format(proc.pid)
        )
    assert proc.returncode == 0
    assert repr(proc) == repr_template.format("exited with status 0")

    async with Process(EXIT_FALSE) as proc:
        pass
    assert proc.returncode == 1
    assert repr(proc) == "<trio.Process {!r}: {}>".format(
        EXIT_FALSE, "exited with status 1"
    )


async def test_multi_wait():
    async with Process(SLEEP(10)) as proc:
        async with _core.open_nursery() as nursery:
            nursery.start_soon(proc.wait)
            nursery.start_soon(proc.wait)
            nursery.start_soon(proc.wait)
            await wait_all_tasks_blocked()
            proc.kill()


async def test_kill_when_context_cancelled():
    with move_on_after(0) as scope:
        async with Process(SLEEP(10)) as proc:
            assert proc.poll() is None
            # Process context entry is synchronous, so this is the
            # only checkpoint:
            await sleep_forever()
    assert scope.cancelled_caught
    assert got_signal(proc, SIGKILL)
    assert repr(proc) == "<trio.Process {!r}: {}>".format(
        SLEEP(10), "exited with signal 9 (our fault)"
        if posix else "exited with status 1 (our fault)"
    )


COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR = python(
    "data = sys.stdin.buffer.read(); "
    "sys.stdout.buffer.write(data); "
    "sys.stderr.buffer.write(data[::-1])"
)


async def test_pipes():
    async with Process(
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


# Subprocess for testing back-and-forth I/O. Works like so:
# in: 32\n
# out: 0000...0000\n (32 zeroes)
# err: 1111...1111\n (64 ones)
# in: 10\n
# out: 2222222222\n (10 twos)
# err: 3333....3333\n (20 threes)
# in: EOF
# out: EOF
# err: EOF
INTERACTIVE_DEMO = python(
    "idx = 0\n"
    "while True:\n"
    "    line = sys.stdin.readline()\n"
    "    if line == '': break\n"
    "    request = int(line.strip())\n"
    "    print(str(idx * 2) * request)\n"
    "    print(str(idx * 2 + 1) * request * 2, file=sys.stderr)\n"
    "    idx += 1\n"
)


async def test_interactive():
    # Test some back-and-forth with a subprocess. This one works like so:

    async with Process(
        INTERACTIVE_DEMO,
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


async def test_run():
    data = bytes(random.randint(0, 255) for _ in range(2**18))

    result = await run_process(CAT, input=data)
    assert result.command == CAT
    assert result.returncode == 0
    assert result.stdout == data
    assert result.stderr == b""

    result = await run_process(CAT, stderr=None)
    assert result.command == CAT
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr is None

    result = await run_process(
        COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR, input=data
    )
    assert result.command == COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR
    assert result.returncode == 0
    assert result.stdout == data
    assert result.stderr == data[::-1]

    with pytest.raises(ValueError):
        # can't use both input and stdin
        await run_process(CAT, input=b"la di dah", stdin=subprocess.PIPE)


@slow
async def test_run_timeout():
    data = b"1" * 65536 + b"2" * 65536 + b"3" * 65536
    child_script = """
import sys, time
sys.stdout.buffer.write(sys.stdin.buffer.read(32768))
time.sleep(10)
sys.stdout.buffer.write(sys.stdin.buffer.read())
"""

    with move_on_after(1):
        result = await run_process(
            [sys.executable, "-c", child_script],
            input=data,
            preserve_result=True
        )
    assert result.cancelled
    assert not result.failed
    assert got_signal(result, SIGKILL)
    assert result.stdout == data[:32768]
    assert result.stderr == b""


async def test_run_check():
    cmd = python("sys.stderr.buffer.write(b'test\\n'); sys.exit(1)")
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        await run_process(cmd, stdout=None)
    assert excinfo.value.cmd == cmd
    assert excinfo.value.returncode == 1
    assert excinfo.value.stderr == b"test\n"
    assert excinfo.value.stdout is None

    result = await run_process(cmd, check=False)
    assert result.command == cmd
    assert result.stdout == b""
    assert result.stderr == b"test\n"
    assert result.returncode == 1


async def test_run_with_broken_pipe():
    result = await run_process(
        [sys.executable, "-c", "import sys; sys.stdin.close()"],
        input=b"x" * 131072
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == b""


async def test_stderr_stdout():
    async with Process(
        COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ) as proc:
        assert proc.stdout is not None
        assert proc.stderr is None

    result = await run_process(
        COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR,
        input=b"1234",
        stderr=subprocess.STDOUT,
    )
    assert result.returncode == 0
    assert result.stdout == b"12344321"
    assert result.stderr is None

    # this one hits the branch where stderr=STDOUT but stdout
    # is not redirected
    result = await run_process(CAT, stdout=None, stderr=subprocess.STDOUT)
    assert result.returncode == 0
    assert result.stdout is None
    assert result.stderr is None

    if posix:
        try:
            r, w = os.pipe()

            async with Process(
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
        Process(["ls"], encoding="utf-8")
    assert "unbuffered byte streams" in str(excinfo.value)
    assert "the 'encoding' option is not supported" in str(excinfo.value)

    if posix:
        with pytest.raises(TypeError) as excinfo:
            Process(["ls"], shell=True)
        with pytest.raises(TypeError) as excinfo:
            Process("ls", shell=False)


async def test_signals():
    async def test_one_signal(send_it, signum):
        with move_on_after(1.0) as scope:
            async with Process(SLEEP(3600)) as proc:
                send_it(proc)
        assert not scope.cancelled_caught
        assert not proc.failed
        if posix:
            assert proc.returncode == -signum
        else:
            assert proc.returncode != 0

    await test_one_signal(Process.kill, SIGKILL)
    await test_one_signal(Process.terminate, SIGTERM)
    if posix:
        await test_one_signal(lambda proc: proc.send_signal(SIGINT), SIGINT)


async def test_delegate():
    # The whole point of delegate_to_process is that its I/O doesn't go
    # through us, so there's not that much we can test, but we can at least
    # run the code

    result = await delegate_to_process(EXIT_TRUE)
    assert result.stdout is result.stderr is None

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        await delegate_to_process(EXIT_FALSE)
    assert excinfo.value.stdout is excinfo.value.stderr is None

    with pytest.raises(ValueError):
        await delegate_to_process(CAT, input=b"input not allowed")


# no sleeps but it takes over a second on my machine
@slow
async def test_not_a_failure_if_we_signal():
    async def do_test(
        which_signal,
        send_it,
        wait_for_signal=True,
        exit_status=None,  # None = propagate the signal
    ):
        code = []
        if wait_for_signal and exit_status is not None:
            if not posix or which_signal == signal.SIGKILL:
                # can't handle this signal, so don't try
                exit_status = None
            else:
                code.extend(
                    [
                        "import signal",
                        "def handle(sig, frame):",
                        "    sys.exit({})".format(exit_status),
                        "signal.signal({}, handle)".format(which_signal),
                    ]
                )
        code.extend([
            "import sys",
            "sys.stdout.buffer.write(b'.')",
        ])
        if not wait_for_signal:
            code.append("sys.exit({})".format(exit_status))
        else:
            code.extend([
                "import time",
                "time.sleep(10)",
            ])

        with fail_after(1):
            async with Process(
                python("\n".join(code)), stdout=subprocess.PIPE
            ) as proc:
                # Wait for process to start up and install signal handler
                # if any
                await proc.stdout.receive_some(1)

                # Secretly wait for the process to exit if we're trying to
                # test the exited-before-we-sent-it case; otherwise the
                # signal-sending could race with the exit. (We don't check
                # for exit through the Process object because we don't want
                # it to know the process exited.)
                if not wait_for_signal:
                    proc._proc.wait()  # synchronous Popen.wait()

                send_it(proc)
                await proc.wait()

        if exit_status is not None:
            assert proc.returncode == exit_status
            assert proc.failed == (
                proc.returncode != 0 and
                (not wait_for_signal or which_signal != signal.SIGTERM)
            )
        else:
            assert wait_for_signal
            assert proc.returncode == (-which_signal if posix else 1)
            assert not proc.failed

    def sender(sig):
        return partial(Process.send_signal, sig=sig)

    # test exit on unhandled terminate/kill and exit before
    # attempt to terminate/kill
    from signal import SIGTERM as TERM
    try:
        from signal import SIGKILL as KILL
    except ImportError:
        KILL = TERM
    for exit_status in (None, 0, 1, 42):
        wait = exit_status is None
        await do_test(TERM, sender(TERM), wait, exit_status)
        await do_test(TERM, Process.terminate, wait, exit_status)
        await do_test(KILL, sender(KILL), wait, exit_status)
        await do_test(KILL, Process.kill, wait, exit_status)

    if posix:
        # test exit on handled terminate -- never counted as fail
        for exit_status in (0, 1, 42):
            await do_test(TERM, sender(TERM), True, exit_status)
            await do_test(TERM, Process.terminate, True, exit_status)

        # test a non-TERM signal
        HUP = signal.SIGHUP
        await do_test(HUP, sender(HUP))  # exit on unhandled is OK
        for exit_status in (0, 1, 42):
            # exit before delivered & exit on handled are both fails
            # if the status is nonzero
            await do_test(HUP, sender(HUP), False, exit_status)
            await do_test(HUP, sender(HUP), True, exit_status)


async def test_not_a_failure_if_we_break_their_pipe():
    # Actually broke their pipe
    async with Process(YES, stdout=subprocess.PIPE) as proc:
        await proc.stdout.aclose()
    assert proc.returncode != 0
    assert not proc.failed

    # Looks like we could've
    async with Process(
        EXIT_FALSE, stdout=subprocess.PIPE
    ) as proc:
        await proc.stdout.aclose()
    assert proc.returncode == 1
    assert not proc.failed

    # ... and we noticed via poll()
    async with Process(
        EXIT_FALSE, stdout=subprocess.PIPE
    ) as proc:
        while proc.poll() is not None:
            pass
        await proc.stdout.aclose()
    assert proc.returncode == 1
    assert not proc.failed

    # Works on stderr too
    async with Process(
        EXIT_FALSE, stderr=subprocess.PIPE
    ) as proc:
        await proc.stderr.aclose()
    assert proc.returncode == 1
    assert not proc.failed

    # Closed after process exited --> not our fault
    async with Process(
        EXIT_FALSE, stdout=subprocess.PIPE
    ) as proc:
        await proc.wait()
        await proc.stdout.aclose()
    assert proc.returncode == 1
    assert proc.failed

    # Closed after process exited and we noticed via poll()
    async with Process(
        EXIT_FALSE, stdout=subprocess.PIPE
    ) as proc:
        while proc.poll() is None:
            pass
        await proc.stdout.aclose()
    assert proc.returncode == 1
    assert proc.failed


async def test_run_in_background():
    # Test signaling a background process
    async with _core.open_nursery() as nursery:
        proc = await nursery.start(
            run_process, python("import time; time.sleep(5)")
        )
        assert proc.returncode is None
        nursery.cancel_scope.cancel()
    assert got_signal(proc, SIGKILL)
    assert not proc.failed

    # Test closing a background process's stream
    async with _core.open_nursery() as nursery:
        proc = await nursery.start(run_process, YES)
        await proc.stdout.aclose()
    assert proc.returncode == 1  # exits due to BrokenPipeError
    assert not proc.failed  # we closed their pipe first, so it's our fault

    # Test a background process failing
    with pytest.raises(subprocess.CalledProcessError):
        async with _core.open_nursery() as nursery:
            await nursery.start(run_process, EXIT_FALSE)


@slow
async def test_shutdown():
    # test some normal non-shutdown cases with a shutdown configured,
    # to make sure it doesn't interfere when not used
    with fail_after(2):
        await run_process(EXIT_TRUE, shutdown_timeout=1)
        with pytest.raises(subprocess.CalledProcessError):
            await run_process(EXIT_FALSE, shutdown_timeout=1)
        data = b"hi" * 16384
        assert data == (
            await run_process(CAT, input=data, shutdown_timeout=1)
        ).stdout
        result = await run_process(
            COPY_STDIN_TO_STDOUT_AND_BACKWARD_TO_STDERR,
            input=b"1234",
            shutdown_timeout=1,
        )
        assert result.stdout == b"1234"
        assert result.stderr == b"4321"

    if posix:
        # test a successful shutdown
        shutdown_flags = dict(shutdown_signal=signal.SIGINT)

        SHUTDOWN_HANDLED = python(
            r"""import itertools, time
try:
    for idx in itertools.count():
        sys.stdout.buffer.write(b"%d\n" % idx)
        time.sleep(0.1)
except KeyboardInterrupt:
    sys.stdout.buffer.write(b"exiting\n")
"""
        )
        with move_on_after(1):
            result = await run_process(
                SHUTDOWN_HANDLED,
                preserve_result=True,
                shutdown_timeout=1,
                **shutdown_flags
            )
        assert result.cancelled
        assert result.returncode == 0
        output = result.stdout.split(b"\n")

        # we set a timeout of 1 sec; allow anywhere between 5 and 12
        # lines of every-0.1-sec output to account for possible slow
        # startup
        assert output.pop() == b""
        assert output.pop() == b"exiting"
        assert 5 <= len(output) <= 12
        assert all(line == b"%d" % idx for idx, line in enumerate(output))

        # test a manual shutdown
        async with open_process(SHUTDOWN_HANDLED, **shutdown_flags) as stream:
            async with _core.open_nursery() as nursery:
                # must wait to receive something to ensure we're
                # inside the try block before we interrupt
                await stream.receive_some(1024)
                nursery.start_soon(stream.process.shutdown)
                output = []
                while True:
                    chunk = await stream.receive_some(1024)
                    if chunk == b"":
                        break
                    output.append(chunk)
                assert b"".join(output).endswith(b"exiting\n")

        # test a shutdown that times out
        SHUTDOWN_IGNORED = python(
            r"""import time
try:
    sys.stdout.buffer.write(b"running\n")
    time.sleep(10)
except KeyboardInterrupt:
    sys.stdout.buffer.write(b"muahahaha\n")
    time.sleep(10)
"""
        )
        with move_on_after(0.5):
            result = await run_process(
                SHUTDOWN_IGNORED,
                preserve_result=True,
                shutdown_timeout=0.5,
                **shutdown_flags
            )
        assert result.cancelled
        assert got_signal(result, SIGKILL)
        assert result.stdout == b"running\n" + b"muahahaha\n"

        # make sure cancel gets raised even if it's momentary
        with _core.open_cancel_scope() as outer_scope:
            with _core.open_cancel_scope() as inner_scope:
                async with _core.open_nursery() as nursery:
                    proc = await nursery.start(
                        partial(
                            run_process,
                            SLEEP(10),
                            shutdown_timeout=0.5,
                            **shutdown_flags
                        )
                    )
                    await wait_all_tasks_blocked()
                    # This will immediately cancel the task waiting
                    # in Process.join:
                    outer_scope.cancel()
                    # And this will prevent it from executing any
                    # further checkpoints in a cancelled state:
                    inner_scope.shield = True

        # The process still gets killed
        assert got_signal(proc, SIGINT)
        # The cancel still gets propagated
        assert outer_scope.cancelled_caught

    # test a close-pipes-and-wait style of shutdown (works on Windows too)
    with _core.open_cancel_scope() as scope:
        async with open_process(
            INTERACTIVE_DEMO,
            stderr=subprocess.DEVNULL,
            shutdown_signal=0,
            shutdown_timeout=0.5,
        ) as stream:
            newline = b"\n" if posix else b"\r\n"
            await stream.wait_send_all_might_not_block()  # for coverage
            await stream.send_all(b"4" + newline)

            response = b""
            target = b"0000" + newline
            while len(response) < len(target):
                response += await stream.receive_some(
                    len(target) - len(response)
                )
            assert response == target
            scope.cancel()

            # Make sure we're closing the pipes due to the shutdown,
            # not just due to exiting the open_process ``async with`` block
            with _core.open_cancel_scope(shield=True):
                await stream.process.wait()

    assert scope.cancelled_caught
    assert stream.process.returncode == 0


async def test_process_stream_unavail():
    async with Process(EXIT_TRUE) as proc:
        stream = ProcessStream(proc)
        with pytest.raises(_core.ClosedResourceError):
            with assert_checkpoints():
                await stream.send_all(b"hi")
        with pytest.raises(_core.ClosedResourceError):
            with assert_checkpoints():
                await stream.receive_some(1024)


@pytest.mark.skipif(not posix, reason="POSIX specific")
async def test_wait_reapable_fails():
    old_sigchld = signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    try:
        # With SIGCHLD disabled, the wait() syscall will wait for the
        # process to exit but then fail with ECHILD. Make sure we
        # support this case as the stdlib subprocess module does.
        async with Process(SLEEP(3600)) as proc:
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
