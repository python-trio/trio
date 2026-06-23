from __future__ import annotations

import errno
import os
import re
import signal
import sys
from typing import Protocol

import pytest

from trio._tests.pytest_plugin import SKIP_OPTIONAL_IMPORTS

if sys.platform == "win32" and sys.version_info < (3, 13):
    pytest.skip("PyPI pyrepl only supports unix", allow_module_level=True)

try:
    import trio._repl
except SystemExit:
    assert SKIP_OPTIONAL_IMPORTS
    pytest.skip(
        "we exit out of the REPL quickly if no pyrepl is found",
        allow_module_level=True,
    )


class RawInput(Protocol):
    def __call__(self, prompt: str = "") -> str: ...


def build_raw_input(cmds: list[str]) -> RawInput:
    """
    Pass in a list of strings.
    Returns a callable that returns each string, each time its called
    When there are not more strings to return, raise EOFError
    """
    cmds_iter = iter(cmds)
    prompts = []

    def _raw_helper(prompt: str = "") -> str:
        prompts.append(prompt)
        try:
            return next(cmds_iter)
        except StopIteration:
            raise EOFError from None

    return _raw_helper


def test_build_raw_input() -> None:
    """Quick test of our helper function."""
    raw_input = build_raw_input(["cmd1"])
    assert raw_input() == "cmd1"
    with pytest.raises(EOFError):
        raw_input()


async def test_basic_interaction(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Run some basic commands through the interpreter while capturing stdout.
    Ensure that the interpreted prints the expected results.
    """
    console = trio._repl.TrioInteractiveConsole()
    raw_input = build_raw_input(
        [
            # evaluate simple expression and recall the value
            "x = 1",
            "print(f'{x=}')",
            # Literal gets printed
            "'hello'",
            # define and call sync function
            "def func():",
            "  print(x + 1)",
            "",
            "func()",
            # define and call async function
            "async def afunc():",
            "  return 4",
            "",
            "await afunc()",
            # import works
            "import sys",
            "sys.stdout.write('hello stdout\\n')",
        ],
    )
    monkeypatch.setattr(console, "raw_input", raw_input)
    await trio._repl.run_repl(console)
    out, _err = capsys.readouterr()
    assert out.splitlines() == ["x=1", "'hello'", "2", "4", "hello stdout", "13"]


async def test_system_exits_quit_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    console = trio._repl.TrioInteractiveConsole()
    raw_input = build_raw_input(
        [
            "raise SystemExit",
        ],
    )
    monkeypatch.setattr(console, "raw_input", raw_input)
    with pytest.raises(SystemExit):
        await trio._repl.run_repl(console)


async def test_KI_interrupts(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console = trio._repl.TrioInteractiveConsole()
    raw_input = build_raw_input(
        [
            "import signal, trio, trio.lowlevel",
            "async def f():",
            "  trio.lowlevel.spawn_system_task("
            "    trio.to_thread.run_sync,"
            "    signal.raise_signal, signal.SIGINT,"
            "  )",  # just awaiting this kills the test runner?!
            "  await trio.sleep_forever()",
            "  print('should not see this')",
            "",
            "await f()",
            "print('AFTER KeyboardInterrupt')",
        ],
    )
    monkeypatch.setattr(console, "raw_input", raw_input)
    await trio._repl.run_repl(console)
    out, err = capsys.readouterr()
    assert "KeyboardInterrupt" in err
    assert "should" not in out
    assert "AFTER KeyboardInterrupt" in out


async def test_system_exits_in_exc_group(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console = trio._repl.TrioInteractiveConsole()
    raw_input = build_raw_input(
        [
            "import sys",
            "if sys.version_info < (3, 11):",
            "  from exceptiongroup import BaseExceptionGroup",
            "",
            "raise BaseExceptionGroup('', [RuntimeError(), SystemExit()])",
            "print('AFTER BaseExceptionGroup')",
        ],
    )
    monkeypatch.setattr(console, "raw_input", raw_input)
    await trio._repl.run_repl(console)
    out, _err = capsys.readouterr()
    # assert that raise SystemExit in an exception group
    # doesn't quit
    assert "AFTER BaseExceptionGroup" in out


async def test_system_exits_in_nested_exc_group(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console = trio._repl.TrioInteractiveConsole()
    raw_input = build_raw_input(
        [
            "import sys",
            "if sys.version_info < (3, 11):",
            "  from exceptiongroup import BaseExceptionGroup",
            "",
            "raise BaseExceptionGroup(",
            "  '', [BaseExceptionGroup('', [RuntimeError(), SystemExit()])])",
            "print('AFTER BaseExceptionGroup')",
        ],
    )
    monkeypatch.setattr(console, "raw_input", raw_input)
    await trio._repl.run_repl(console)
    out, _err = capsys.readouterr()
    # assert that raise SystemExit in an exception group
    # doesn't quit
    assert "AFTER BaseExceptionGroup" in out


async def test_base_exception_captured(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console = trio._repl.TrioInteractiveConsole()
    raw_input = build_raw_input(
        [
            # The statement after raise should still get executed
            "raise BaseException",
            "print('AFTER BaseException')",
        ],
    )
    monkeypatch.setattr(console, "raw_input", raw_input)
    await trio._repl.run_repl(console)
    out, err = capsys.readouterr()
    assert "_threads.py" not in err
    assert "_repl.py" not in err
    assert "AFTER BaseException" in out


async def test_exc_group_captured(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console = trio._repl.TrioInteractiveConsole()
    raw_input = build_raw_input(
        [
            # The statement after raise should still get executed
            "raise ExceptionGroup('', [KeyError()])",
            "print('AFTER ExceptionGroup')",
        ],
    )
    monkeypatch.setattr(console, "raw_input", raw_input)
    await trio._repl.run_repl(console)
    out, _err = capsys.readouterr()
    assert "AFTER ExceptionGroup" in out


async def test_base_exception_capture_from_coroutine(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console = trio._repl.TrioInteractiveConsole()
    raw_input = build_raw_input(
        [
            "async def async_func_raises_base_exception():",
            "  raise BaseException",
            "",
            # This will raise, but the statement after should still
            # be executed
            "await async_func_raises_base_exception()",
            "print('AFTER BaseException')",
        ],
    )
    monkeypatch.setattr(console, "raw_input", raw_input)
    await trio._repl.run_repl(console)
    out, err = capsys.readouterr()
    assert "_threads.py" not in err
    assert "_repl.py" not in err
    assert "AFTER BaseException" in out


def start_repl() -> tuple[int, int]:
    assert sys.platform != "win32"

    import pty

    # NOTE: this cannot be subprocess.Popen because pty.fork
    #       does some magic to set the controlling terminal.
    # (which I don't know how to replicate... so I copied this
    # structure from pty.spawn...)
    pid, pty_fd = pty.fork()  # type: ignore[attr-defined,unused-ignore]
    if pid == 0:  # pragma: no cover
        os.execlp(sys.executable, *[sys.executable, "-u", "-m", "trio"])

    return pid, pty_fd


def read_until(buffer: bytearray, expected: bytes, fd: int) -> None:
    while expected not in strip_some_escape_chars(buffer):
        try:
            res = os.read(fd, 4096)
        except OSError as e:
            # process died
            assert e.errno == errno.EIO  # noqa: PT017
            break

        if res == b"":
            break
        buffer += res

    if b"_pyrepl.unix_console.InvalidTerminal" in buffer:
        pytest.skip("this PTY doesn't support the necessary operations")


def write_out(text: bytes, buffer: bytearray, fd: int) -> None:
    # for some reason this is required for pypy :(
    small_buffer = bytearray()
    for i, char in enumerate(text):
        os.write(fd, bytes([char]))
        read_until(small_buffer, text[: i + 1], fd)

    buffer += small_buffer


def strip_some_escape_chars(buffer: bytearray) -> bytes:
    # https://superuser.com/a/380778
    return re.sub(b"\x1b" + rb"\[.*?[\x40-\x7E]", b"", buffer)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Python doesn't support ConPTY, so we can't make the right environment for the REPL.",
)
def test_main_entrypoint() -> None:
    """
    Basic smoke test when running via the package __main__ entrypoint.
    """
    pid, fd = start_repl()

    # setup:
    buffer = bytearray()
    read_until(buffer, b"import trio", fd)

    buffer = buffer.split(b"import trio")[-1]
    read_until(buffer, b">>>", fd)

    # just exit:
    write_out(b"exit()", buffer, fd)
    os.write(fd, b"\n")

    # and flush any output:
    buffer = bytearray()
    read_until(buffer, b"something impossible", fd)

    assert os.waitpid(pid, 0)[1] == 0


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Python doesn't support ConPTY, so we can't make the right environment for the REPL.",
)
def test_repl_ki() -> None:
    pid, fd = start_repl()

    # setup:
    buffer = bytearray()
    read_until(buffer, b"import trio", fd)

    buffer = buffer.split(b"import trio")[-1]
    read_until(buffer, b">>>", fd)

    # sanity check:
    print(buffer.decode())
    buffer = bytearray()
    write_out(b'print("hello!") # mark', buffer, fd)
    os.write(fd, b"\n")
    read_until(buffer, b"# mark", fd)

    buffer = buffer.split(b"# mark")[-1]
    read_until(buffer, b">>>", fd)

    assert buffer.count(b"hello!") == 1

    # press ctrl+c
    print(buffer.decode())
    if trio._repl.CPYTHON_VENDOR:
        # would you believe me if I told you pyrepl has a bug where
        # `UnixConsole.get_event(block=False)`... blocks? well anyways,
        # that means this part of the test doesn't work.
        buffer = bytearray()
        os.kill(pid, signal.SIGINT)
        read_until(buffer, b">>>", fd)

        assert b"KeyboardInterrupt" in buffer

        # press ctrl+c later
        print(buffer.decode())
        buffer = bytearray()
        write_out(b'print("hello!") # mark', buffer, fd)
        read_until(buffer, b"# mark", fd)

        buffer = bytearray()
        os.kill(pid, signal.SIGINT)
        read_until(buffer, b">>>", fd)

        assert b"KeyboardInterrupt" in buffer
    os.close(fd)
    os.waitpid(pid, 0)[1]
