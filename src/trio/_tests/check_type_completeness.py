#!/usr/bin/env python3
from __future__ import annotations

# this file is not run as part of the tests, instead it's run standalone from check.sh
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

# the result file is not marked in MANIFEST.in so it's not included in the package
failed = False

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


def check_zero(key: str, current_dict: Mapping[str, float]) -> None:
    global failed
    if current_dict[key] != 0:
        failed = True
        print(f"ERROR: {key} is {current_dict[key]}")


def check_type(args: argparse.Namespace, platform: str) -> int:
    res = run_pyright(platform)
    current_result = json.loads(res.stdout)

    if res.stderr:
        print(res.stderr)

    if args.full_diagnostics_file:
        with open(args.full_diagnostics_file, "w") as f:
            json.dump(current_result, f, sort_keys=True, indent=4)

    missingFunctionDocStringCount = current_result["typeCompleteness"][
        "missingFunctionDocStringCount"
    ]
    # missingClassDocStringCount = current_result["typeCompleteness"][
    #    "missingClassDocStringCount"
    # ]

    for symbol in current_result["typeCompleteness"]["symbols"]:
        diagnostics = symbol["diagnostics"]
        if not diagnostics:
            continue
        for diagnostic in diagnostics:
            if diagnostic["message"].startswith("No docstring found for"):
                # check if it actually has a docstring at runtime
                # this is rickety and incomplete - but works for the current
                # missing docstrings
                name_parts = symbol["name"].split(".")
                if name_parts[1] == "_core":  # noqa: SIM108
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
                        missingFunctionDocStringCount -= 1
                        continue
                if obj.__doc__:
                    missingFunctionDocStringCount -= 1
                    continue

            if diagnostic["message"] in printed_diagnostics:
                continue
            print(diagnostic["message"])
            printed_diagnostics.add(diagnostic["message"])

        continue

    if missingFunctionDocStringCount > 0:
        print(
            f"ERROR: missingFunctionDocStringCount is {missingFunctionDocStringCount}"
        )
        failed = True

    for key in "errorCount", "warningCount", "informationCount":
        check_zero(key, current_result["summary"])

    for key in (
        # "missingFunctionDocStringCount",
        "missingClassDocStringCount",
        "missingDefaultParamCount",
        # "completenessScore",
    ):
        check_zero(key, current_result["typeCompleteness"])

    for key in ("withUnknownType", "withAmbiguousType"):
        check_zero(key, current_result["typeCompleteness"]["exportedSymbolCounts"])

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
