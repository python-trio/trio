import subprocess
import sys

import pytest

import trio._repl


def build_raw_input(cmds):
    """
    Pass in a list of strings.
    Returns a callable that returns each string, each time its called
    When there are not more strings to return, raise EOFError
    """
    cmds_iter = iter(cmds)
    prompts = []

    def _raw_helper(prompt=""):
        prompts.append(prompt)
        try:
            return next(cmds_iter)
        except StopIteration:
            raise EOFError from None

    return _raw_helper


def test_build_raw_input():
    """Quick test of our helper function."""
    raw_input = build_raw_input(["cmd1"])
    assert raw_input() == "cmd1"
    with pytest.raises(EOFError):
        raw_input()


async def test_basic_interaction(capsys):
    """
    Run some basic commands through the interpreter while capturing stdout.
    Ensure that the interpreted prints the expected results.
    """
    console = trio._repl.TrioInteractiveConsole(repl_locals={"trio": trio})
    console.raw_input = build_raw_input(
        [
            # evaluate simple expression and recall the value
            "x = 1",
            "print(f'{x=}')",
            # Literal gets printed
            "'hello'",
            # define and call sync function
            "def func():",
            "  print(x)",
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
        ]
    )
    await console.task(console.interact)
    out, err = capsys.readouterr()
    assert out.splitlines() == ["x=1", "'hello'", "1", "4", "hello stdout", "13"]


async def test_system_exits_quit_interpreter():
    console = trio._repl.TrioInteractiveConsole(repl_locals={"trio": trio})
    console.raw_input = build_raw_input(
        [
            # evaluate simple expression and recall the value
            "raise SystemExit",
        ]
    )
    with pytest.raises(SystemExit):
        await console.task(console.interact)


async def test_base_exception_captured(capsys):
    console = trio._repl.TrioInteractiveConsole(repl_locals={"trio": trio})
    console.raw_input = build_raw_input(
        [
            # The statement after raise should still get executed
            "raise BaseException",
            "print('AFTER BaseException')",
        ]
    )
    await console.task(console.interact)
    out, err = capsys.readouterr()
    assert "AFTER BaseException" in out


async def test_base_exception_capture_from_coroutine(capsys):
    console = trio._repl.TrioInteractiveConsole(repl_locals={"trio": trio})
    console.raw_input = build_raw_input(
        [
            "async def async_func_raises_base_exception():",
            "  raise BaseException",
            "",
            # This will raise, but the statement after should still
            # be executed
            "await async_func_raises_base_exception()",
            "print('AFTER BaseException')",
        ]
    )
    await console.task(console.interact)
    out, err = capsys.readouterr()
    assert "AFTER BaseException" in out


def test_main_entrypoint():
    """
    Basic smoke test when running via the package __main__ entrypoint.
    """
    repl = subprocess.run([sys.executable, "-m", "trio"], input=b"exit()")
    assert repl.returncode == 0
