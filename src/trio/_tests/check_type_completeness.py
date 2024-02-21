#!/usr/bin/env python3
from __future__ import annotations

# this file is not run as part of the tests, instead it's run standalone from check.sh
import argparse
import json
import subprocess
import sys
from pathlib import Path

import trio
import trio.testing

printed_diagnostics: set[str] = set()


# TODO: consider checking manually without `--ignoreexternal`, and/or
# removing it from the below call later on.
def run_pyright(platform: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            "pyright",
            # Specify a platform and version to keep imported modules consistent.
            f"--pythonplatform={platform}",
            "--pythonversion=3.8",
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
    assert trio.testing

    # figure out what part of the name is the module, so we can "import" it
    name_parts = name.split(".")
    split_i = 1
    if name_parts[1] == "tests":
        return True
    if name_parts[1] in ("_core", "testing"):  # noqa: SIM108
        split_i = 2
    else:
        split_i = 1
    module = sys.modules[".".join(name_parts[:split_i])]

    # traverse down the remaining identifiers with getattr
    obj = module
    try:
        for obj_name in name_parts[split_i:]:
            obj = getattr(obj, obj_name)
    except AttributeError as exc:
        # asynciowrapper does funky getattr stuff
        if "AsyncIOWrapper" in str(exc) or name in (
            # Symbols not existing on all platforms, so we can't dynamically inspect them.
            # Manually confirmed to have docstrings but pyright doesn't see them due to
            # export shenanigans.
            # darwin
            "trio.lowlevel.current_kqueue",
            "trio.lowlevel.monitor_kevent",
            "trio.lowlevel.wait_kevent",
            "trio._core._io_kqueue._KqueueStatistics",
            # windows
            "trio._socket.SocketType.share",
            "trio._core._io_windows._WindowsStatistics",
            "trio._core._windows_cffi.Handle",
            "trio.lowlevel.current_iocp",
            "trio.lowlevel.monitor_completion_key",
            "trio.lowlevel.readinto_overlapped",
            "trio.lowlevel.register_with_iocp",
            "trio.lowlevel.wait_overlapped",
            "trio.lowlevel.write_overlapped",
            "trio.lowlevel.WaitForSingleObject",
            "trio.socket.fromshare",
            # these are erroring on all platforms
            "trio._highlevel_generic.StapledStream.send_stream",
            "trio._highlevel_generic.StapledStream.receive_stream",
            "trio._ssl.SSLStream.transport_stream",
            "trio._file_io._HasFileNo",
            "trio._file_io._HasFileNo.fileno",
        ):
            return True

        else:
            print(
                f"Pyright sees {name} at runtime, but unable to getattr({obj.__name__}, {obj_name})."
            )
    return bool(obj.__doc__)


def check_type(
    platform: str, full_diagnostics_file: Path | None, expected_errors: list[object]
) -> list[object]:
    # convince isort we use the trio import
    assert trio

    # run pyright, load output into json
    res = run_pyright(platform)
    current_result = json.loads(res.stdout)

    if res.stderr:
        print(res.stderr)

    if full_diagnostics_file:
        with open(full_diagnostics_file, "a") as f:
            json.dump(current_result, f, sort_keys=True, indent=4)

    errors = []

    for symbol in current_result["typeCompleteness"]["symbols"]:
        category = symbol["category"]
        diagnostics = symbol["diagnostics"]
        name = symbol["name"]
        if not diagnostics:
            if (
                category
                not in ("variable", "symbol", "type alias", "constant", "module")
                and not name.endswith("__")
                and not has_docstring_at_runtime(symbol["name"])
            ):
                print(
                    "not warned by pyright, but missing docstring:",
                    symbol["name"],
                    symbol["category"],
                )
            continue
        for diagnostic in diagnostics:
            message = diagnostic["message"]
            # ignore errors about missing docstrings if they're available at runtime
            if message.startswith("No docstring found for"):
                if has_docstring_at_runtime(symbol["name"]):
                    continue
            else:
                message = f"{name}: {message}"
            # try:
            #    expected_errors.remove(diagnostic)
            #    # decrement count for object
            # except ValueError:
            if message not in expected_errors and message not in printed_diagnostics:
                print(f"new error: {message}")
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

    errors_by_platform_file = Path(__file__).parent / "_check_type_completeness.json"
    if errors_by_platform_file.exists():
        with open(errors_by_platform_file) as f:
            errors_by_platform = json.load(f)
    else:
        errors_by_platform = {"Linux": [], "Windows": [], "Darwin": []}

    changed = False
    for platform in "Linux", "Windows", "Darwin":
        print("*" * 20, f"\nChecking {platform}...")
        errors = check_type(
            platform, full_diagnostics_file, errors_by_platform[platform]
        )

        new_errors = [e for e in errors if e not in errors_by_platform[platform]]
        missing_errors = [e for e in errors_by_platform[platform] if e not in errors]

        if new_errors:
            print(
                f"New errors introduced in `pyright --verifytypes`. Fix them, or ignore them by modifying {errors_by_platform_file}. The latter can be done by pre-commit CI bot."
            )
            # print(new_errors)
            changed = True
        if missing_errors:
            print(
                f"Congratulations, you have resolved existing errors! Please remove them from {errors_by_platform_file}, either manually or with the pre-commit CI bot."
            )
            # print(missing_errors)
            changed = True

        errors_by_platform[platform] = errors
    print("*" * 20)

    if changed and args.overwrite_file:
        with open(errors_by_platform_file, "w") as f:
            json.dump(errors_by_platform, f, indent=4, sort_keys=True)
            # newline at end of file
            f.write("\n")

    # True -> 1 -> non-zero exit value -> error
    return changed


parser = argparse.ArgumentParser()
parser.add_argument("--overwrite-file", action="store_true", default=False)
parser.add_argument("--full-diagnostics-file", type=Path, default=None)
args = parser.parse_args()

assert __name__ == "__main__", "This script should be run standalone"
sys.exit(main(args))
