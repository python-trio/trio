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
    assert trio.testing
    # this is rickety, but works for all current symbols
    name_parts = name.split(".")
    split_i = 1
    if name_parts[1] == "tests":
        return True
    if name_parts[1] in ("_core", "testing"):  # noqa: SIM108
        split_i = 2
    else:
        split_i = 1
    module = sys.modules[".".join(name_parts[:split_i])]
    obj = module
    try:
        for obj_name in name_parts[split_i:]:
            obj = getattr(obj, obj_name)
    except AttributeError as exc:
        # asynciowrapper does funky getattr stuff
        if "AsyncIOWrapper" in str(exc):
            return True
        # raise
        print(exc)
    return bool(obj.__doc__)


def check_type(args: argparse.Namespace, platform: str) -> int:
    # convince isort we use the trio import
    assert trio

    res = run_pyright(platform)
    current_result = json.loads(res.stdout)

    if res.stderr:
        print(res.stderr)

    if args.full_diagnostics_file:
        with open(args.full_diagnostics_file, "w") as f:
            json.dump(current_result, f, sort_keys=True, indent=4)

    counts = {}
    for where, key in (
        (("typeCompleteness",), "missingFunctionDocStringCount"),
        (("typeCompleteness",), "missingClassDocStringCount"),
        (("typeCompleteness",), "missingDefaultParamCount"),
        (("summary",), "errorCount"),
        (("summary",), "warningCount"),
        (("summary",), "informationCount"),
        (("typeCompleteness", "exportedSymbolCounts"), "withUnknownType"),
        (("typeCompleteness", "exportedSymbolCounts"), "withAmbiguousType"),
    ):
        curr_dict = current_result
        for subdict in where:
            curr_dict = curr_dict[subdict]

        counts[key] = curr_dict[key]

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
            if diagnostic["message"].startswith(
                "No docstring found for"
            ) and has_docstring_at_runtime(symbol["name"]):
                if category in ("method", "function"):
                    counts["missingFunctionDocStringCount"] -= 1
                elif category == "class":
                    counts["missingClassDocStringCount"] -= 1
                else:
                    raise AssertionError("This category shouldn't be possible here")
                continue

            if diagnostic["message"] in printed_diagnostics:
                continue
            print(diagnostic["message"])
            printed_diagnostics.add(diagnostic["message"])

        continue

    for name, val in counts.items():
        if val > 0:
            print(f"ERROR: {name} is {val}")
            failed = True

    return int(failed)


def main(args: argparse.Namespace) -> int:
    res = 0
    for platform in "Linux", "Windows", "Darwin":
        print("*" * 20, f"\nChecking {platform}...")
        res += check_type(args, platform)
    print("*" * 20)
    return res


parser = argparse.ArgumentParser()
parser.add_argument("--overwrite-file", action="store_true", default=False)
parser.add_argument("--full-diagnostics-file", type=Path, default=None)
args = parser.parse_args()

assert __name__ == "__main__", "This script should be run standalone"
sys.exit(main(args))
