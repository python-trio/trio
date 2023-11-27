from __future__ import annotations

import gc
import os
import re
import subprocess
import sys
from pathlib import Path
from traceback import extract_tb
from typing import TYPE_CHECKING, Callable, NoReturn, TypeVar

import pytest

from ..._core import open_nursery
from .._multierror import concat_tb
from .tutil import slow

if TYPE_CHECKING:
    from types import TracebackType

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

E = TypeVar("E", bound=BaseException)


class NotHashableException(Exception):
    code: int | None = None

    def __init__(self, code: int) -> None:
        super().__init__()
        self.code = code

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NotHashableException):
            return False
        return self.code == other.code


async def raise_nothashable(code: int) -> NoReturn:
    raise NotHashableException(code)


def raiser1() -> NoReturn:
    raiser1_2()


def raiser1_2() -> NoReturn:
    raiser1_3()


def raiser1_3() -> NoReturn:
    raise ValueError("raiser1_string")


def raiser2() -> NoReturn:
    raiser2_2()


def raiser2_2() -> NoReturn:
    raise KeyError("raiser2_string")


def get_exc(raiser: Callable[[], NoReturn]) -> Exception:
    try:
        raiser()
    except Exception as exc:
        return exc
    raise AssertionError("raiser should always raise")  # pragma: no cover


def get_tb(raiser: Callable[[], NoReturn]) -> TracebackType | None:
    return get_exc(raiser).__traceback__


def test_concat_tb() -> None:
    tb1 = get_tb(raiser1)
    tb2 = get_tb(raiser2)

    # These return a list of (filename, lineno, fn name, text) tuples
    # https://docs.python.org/3/library/traceback.html#traceback.extract_tb
    entries1 = extract_tb(tb1)
    entries2 = extract_tb(tb2)

    tb12 = concat_tb(tb1, tb2)
    assert extract_tb(tb12) == entries1 + entries2

    tb21 = concat_tb(tb2, tb1)
    assert extract_tb(tb21) == entries2 + entries1

    # Check degenerate cases
    assert extract_tb(concat_tb(None, tb1)) == entries1
    assert extract_tb(concat_tb(tb1, None)) == entries1
    assert concat_tb(None, None) is None

    # Make sure the original tracebacks didn't get mutated by mistake
    assert extract_tb(get_tb(raiser1)) == entries1
    assert extract_tb(get_tb(raiser2)) == entries2


async def test_ExceptionGroupNotHashable() -> None:
    exc1 = NotHashableException(42)
    exc2 = NotHashableException(4242)
    exc3 = ValueError()
    assert exc1 != exc2
    assert exc1 != exc3

    with pytest.raises(ExceptionGroup):
        async with open_nursery() as nursery:
            nursery.start_soon(raise_nothashable, 42)
            nursery.start_soon(raise_nothashable, 4242)


@pytest.mark.skipif(
    sys.implementation.name != "cpython", reason="Only makes sense with refcounting GC"
)
def test_ExceptionGroup_catch_doesnt_create_cyclic_garbage() -> None:
    # https://github.com/python-trio/trio/pull/2063
    gc.collect()
    old_flags = gc.get_debug()

    def make_multi() -> NoReturn:
        # make_tree creates cycles itself, so a simple
        raise ExceptionGroup("", [get_exc(raiser1), get_exc(raiser2)])

    try:
        gc.set_debug(gc.DEBUG_SAVEALL)
        with pytest.raises(ExceptionGroup) as excinfo:
            # covers ExceptionGroupCatcher.__exit__ and _multierror.copy_tb
            raise make_multi()
        for exc in excinfo.value.exceptions:
            assert isinstance(exc, (ValueError, KeyError))
        gc.collect()
        assert not gc.garbage
    finally:
        gc.set_debug(old_flags)
        gc.garbage.clear()


def assert_match_in_seq(pattern_list: list[str], string: str) -> None:
    offset = 0
    print("looking for pattern matches...")
    for pattern in pattern_list:
        print("checking pattern:", pattern)
        reobj = re.compile(pattern)
        match = reobj.search(string, offset)
        assert match is not None
        offset = match.end()


def test_assert_match_in_seq() -> None:
    assert_match_in_seq(["a", "b"], "xx a xx b xx")
    assert_match_in_seq(["b", "a"], "xx b xx a xx")
    with pytest.raises(AssertionError):
        assert_match_in_seq(["a", "b"], "xx b xx a xx")


def run_script(name: str) -> subprocess.CompletedProcess[bytes]:
    import trio

    trio_path = Path(trio.__file__).parent.parent
    script_path = Path(__file__).parent / "test_multierror_scripts" / name

    env = dict(os.environ)
    print("parent PYTHONPATH:", env.get("PYTHONPATH"))
    pp = []
    if "PYTHONPATH" in env:  # pragma: no cover
        pp = env["PYTHONPATH"].split(os.pathsep)
    pp.insert(0, str(trio_path))
    pp.insert(0, str(script_path.parent))
    env["PYTHONPATH"] = os.pathsep.join(pp)
    print("subprocess PYTHONPATH:", env.get("PYTHONPATH"))

    cmd = [sys.executable, "-u", str(script_path)]
    print("running:", cmd)
    completed = subprocess.run(
        cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    print("process output:")
    print(completed.stdout.decode("utf-8"))
    return completed


@slow
@pytest.mark.skipif(
    not Path("/usr/lib/python3/dist-packages/apport_python_hook.py").exists(),
    reason="need Ubuntu with python3-apport installed",
)
def test_apport_excepthook_monkeypatch_interaction() -> None:
    completed = run_script("apport_excepthook.py")
    stdout = completed.stdout.decode("utf-8")

    # No warning
    assert "custom sys.excepthook" not in stdout

    # Proper traceback
    assert_match_in_seq(
        ["--- 1 ---", "KeyError", "--- 2 ---", "ValueError"],
        stdout,
    )
