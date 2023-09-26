# this file should only check *small* portions of trio's API.
# (it would be unproductive to write out the API twice :^)

import os
import subprocess
import tempfile
import textwrap

import pytest

type_checkers = []
try:
    import pyright
except:
    pass
else:
    type_checkers.append("pyright")
    del pyright

try:
    import mypy
except:
    pass
else:
    type_checkers.append("mypy")
    del mypy


def check_file(checker: str, contents: str) -> bool:
    contents = textwrap.dedent(contents)
    if checker == "mypy":
        p = subprocess.run(["mypy", "-c", contents])
        return not p.returncode
    elif checker == "pyright":
        with tempfile.TemporaryDirectory() as tdir:
            path = os.path.join(tdir, "check.py")
            with open(path, "w") as f:
                f.write(contents)
            p = subprocess.run(["pyright", path, "--verbose"])
            return not p.returncode
    else:
        raise AssertionError(f"unknown checker {checker}")


@pytest.mark.skipif(type_checkers != ["pyright", "mypy"])
def test_harness() -> None:
    # mypy error only!
    file = """
        import typing_extensions
        import typing

        x = 1
        typing_extensions.assert_type(x, typing.Literal[1])
        """
    assert not check_file("mypy", file)
    assert check_file("pyright", file)

    # pyright error only!
    file = file.replace("typing.Literal[1]", "int")
    assert check_file("mypy", file)
    assert not check_file("pyright", file)


@pytest.mark.parametrize("checker", type_checkers)
def test_socket_functools_wrap(checker) -> None:
    # https://github.com/python-trio/trio/issues/2775#issuecomment-1702267589
    # (except platform independent...)
    assert check_file(
        checker,
        """
        import array
        import socket

        import trio
        import typing_extensions


        async def fn(s: trio.SocketStream) -> None:
            result = await s.socket.sendto(b"a", "h")
            typing_extensions.assert_type(result, int)
        """,
    )
