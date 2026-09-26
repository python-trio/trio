#!/usr/bin/env python3
"""This is a file that wraps calls to `pyright --verifytypes`, achieving two things:
1. give an error if docstrings are missing.
    pyright will give a number of missing docstrings, and error messages, but not exit with a non-zero value.
2. filter out specific errors we don't care about.
    this is largely due to 1, but also because Trio does some very complex stuff and --verifytypes has few to no ways of ignoring specific errors.

If this check is giving you false alarms, you can ignore them by adding logic to `has_docstring_at_runtime`, in the main loop in `check_type`, or by updating the json file.
"""

from __future__ import annotations

# this file is not run as part of the tests, instead it's run standalone from check.sh
import argparse
import inspect
import json
import subprocess
import sys
from pathlib import Path

import trio
import trio.testing

# not needed if everything is working, but if somebody does something to generate
# tons of errors, we can be nice and stop them from getting 3*tons of output
printed_diagnostics: set[str] = set()


# TODO: consider checking manually without `--ignoreexternal`, and/or
# removing it from the below call later on.
def run_pyright(platform: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            "pyright",
            # Specify a platform and version to keep imported modules consistent.
            f"--pythonplatform={platform}",
            "--pythonversion=3.10",
            "--verifytypes=trio",
            "--outputjson",
            "--ignoreexternal",
        ],
        capture_output=True,
    )


def has_docstring_at_runtime(name: str) -> bool:
    """Pyright gives us an object identifier of xx.yy.zz
    This function tries to decompose that into its constituent parts, such that we
    can resolve it, in order to check whether it has a `__doc__` at runtime and
    verifytypes misses it because we're doing overly fancy stuff.
    """
    # This assert is solely for stopping isort from removing our imports of trio & trio.testing
    # It could also be done with isort:skip, but that'd also disable import sorting and the like.
    assert trio.testing is not None

    # figure out what part of the name is the module, so we can "import" it
    name_parts = name.split(".")
    assert name_parts[0] == "trio"
    if name_parts[1] == "tests":
        return True

    # traverse down the remaining identifiers with getattr
    obj = trio
    try:
        for obj_name in name_parts[1:]:
            obj = getattr(obj, obj_name)
    except AttributeError as exc:
        # asynciowrapper does funky getattr stuff
        if "AsyncIOWrapper" in str(exc) or name in (
            # Symbols not existing on all platforms, so we can't dynamically inspect them.
            # Manually confirmed to have docstrings but pyright doesn't see them due to
            # export shenanigans.
            # In theory we could verify these at runtime, probably by running the script separately
            # on separate platforms. It might also be a decent idea to work the other way around,
            # a la test_static_tool_sees_class_members
            # darwin
            "trio._core._io_kqueue._KqueueStatistics",  # confirmed to have docstring
            # windows
            "trio._socket.SocketType.share",  # doesn't have docstring, like other
            # SocketType methods. Shows up here bc method def is wrapped in `if not TYPE_CHECKING`
            "trio._core._io_windows._WindowsStatistics",  # confirmed to have docstring
            "trio._core._windows_cffi.Handle",  # doesn't have docstring, it's basically type alias
            # linux
            # this test will fail on linux, but I don't develop on linux. So the next
            # person to do so is very welcome to open a pull request and populate with
            # objects
            # TODO: these are erroring on all platforms, why?
            # It could be due to the fact that this file runs with
            # `typing.TYPE_CHECKING=False` flag, whereas `pyright` executes
            # with flag `typing.TYPE_CHECKING=True`.
            # `AsyncIOWrapper` has conditional method stubs, only for type checking,
            # and docstring is in real method.
            # In other places, private types are imported (or publicly reexported)
            # when `not TYPE_CHECKING`.
            # This could be why this the whole of this exception handler is like this.
            # If one puts `typing.TYPE_CHECKING=True` before trio imports on top
            # of this file, there's circular import error.
            #
            # _io_poll.py and _io_windows.py and _io_kqueue.py:
            # ```
            # if TYPE_CHECKING:
            #    from .._file_io import _HasFileNo
            # ```
            "trio._file_io._HasFileNo",
            "trio._file_io._HasFileNo.fileno",
            # verified that `HasFileNo` has docstrings
        ):
            return True

        else:
            print(
                f"Pyright sees {name} at runtime, but unable to getattr({obj.__name__}, {obj_name}).",
                file=sys.stderr,
            )
            return False
    doc = inspect.getdoc(obj)
    return bool(doc)


def check_type(
    platform: str,
    full_diagnostics_file: Path | None,
) -> list[object]:
    # convince isort we use the trio import
    assert trio is not None

    # run pyright, load output into json
    res = run_pyright(platform)
    current_result = json.loads(res.stdout)

    if res.stderr:
        print(res.stderr, file=sys.stderr)

    if full_diagnostics_file:
        with open(full_diagnostics_file, "a") as f:
            json.dump(current_result, f, sort_keys=True, indent=4)

    errors = []

    for symbol in current_result["typeCompleteness"]["symbols"]:
        diagnostics = symbol["diagnostics"]
        name = symbol["name"]
        for diagnostic in diagnostics:
            message = diagnostic["message"]
            if name in (
                "trio._path.PosixPath",
                "trio._path.WindowsPath",
            ) and message.startswith("Type of base class "):
                continue

            if name.startswith("trio._path.Path"):
                if message.startswith("No docstring found for"):
                    continue
                if message.startswith(
                    "Type is missing type annotation and could be inferred differently by type checkers",
                ):
                    continue

            # ignore errors about missing docstrings if they're available at runtime
            if message.startswith("No docstring found for"):
                if has_docstring_at_runtime(symbol["name"]):
                    continue
            else:
                # Missing docstring messages include the name of the object.
                # Other errors don't, so we add it.
                message = f"{name}: {message}"
            if message not in printed_diagnostics:
                print(f"new error: {message}", file=sys.stderr)
            errors.append(message)
            printed_diagnostics.add(message)

        continue

    return errors


def main(args: argparse.Namespace) -> int:
    if args.full_diagnostics_file:
        full_diagnostics_file = Path(args.full_diagnostics_file)
        full_diagnostics_file.write_text("")
    else:
        full_diagnostics_file = None

    has_errors = False
    for platform in "Linux", "Windows", "Darwin":
        print("*" * 20, f"\nChecking {platform}...")
        errors = check_type(platform, full_diagnostics_file)

        if errors:
            print(
                "New errors introduced in `pyright --verifytypes`. Fix them.",
                file=sys.stderr,
            )
            has_errors = True

    print("*" * 20)

    # True -> 1 -> non-zero exit value -> error
    return has_errors


parser = argparse.ArgumentParser()
parser.add_argument(
    "--full-diagnostics-file",
    type=Path,
    default=None,
    help="Use this for debugging, it will dump the output of all three pyright runs by platform into this file.",
)
args = parser.parse_args()

assert __name__ == "__main__", "This script should be run standalone"
sys.exit(main(args))
