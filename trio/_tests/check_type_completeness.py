#!/usr/bin/env python3
from __future__ import annotations

# this file is not run as part of the tests, instead it's run standalone from check.sh
import argparse
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

# the result file is not marked in MANIFEST.in so it's not included in the package
failed = False


def get_result_file_name(platform: str) -> Path:
    return Path(__file__).parent / f"verify_types_{platform.lower()}.json"


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


def check_less_than(
    key: str,
    current_dict: Mapping[str, int | float],
    last_dict: Mapping[str, int | float],
    /,
    invert: bool = False,
) -> None:
    global failed
    current = current_dict[key]
    last = last_dict[key]
    assert isinstance(current, (float, int))
    assert isinstance(last, (float, int))
    if current == last:
        return
    if (current > last) ^ invert:
        failed = True
        print("ERROR: ", end="")
    strcurrent = f"{current:.4}" if isinstance(current, float) else str(current)
    strlast = f"{last:.4}" if isinstance(last, float) else str(last)
    print(
        f"{key} has gone {'down' if current<last else 'up'} from {strlast} to {strcurrent}"
    )


def check_zero(key: str, current_dict: Mapping[str, float]) -> None:
    global failed
    if current_dict[key] != 0:
        failed = True
        print(f"ERROR: {key} is {current_dict[key]}")


def check_type(args: argparse.Namespace, platform: str) -> int:
    print("*" * 20, "\nChecking type completeness hasn't gone down...")

    res = run_pyright(platform)
    current_result = json.loads(res.stdout)
    py_typed_file: Path | None = None

    # check if py.typed file was missing
    if (
        current_result["generalDiagnostics"]
        and current_result["generalDiagnostics"][0]["message"]
        == "No py.typed file found"
    ):
        print("creating py.typed")
        py_typed_file = (
            Path(current_result["typeCompleteness"]["packageRootDirectory"])
            / "py.typed"
        )
        py_typed_file.write_text("")

        res = run_pyright(platform)
        current_result = json.loads(res.stdout)

    if res.stderr:
        print(res.stderr)

    last_result = json.loads(get_result_file_name(platform).read_text())

    for key in "errorCount", "warningCount", "informationCount":
        check_zero(key, current_result["summary"])

    for key, invert in (
        ("missingFunctionDocStringCount", False),
        ("missingClassDocStringCount", False),
        ("missingDefaultParamCount", False),
        ("completenessScore", True),
    ):
        check_less_than(
            key,
            current_result["typeCompleteness"],
            last_result["typeCompleteness"],
            invert=invert,
        )

    for key, invert in (
        ("withUnknownType", False),
        ("withAmbiguousType", False),
        ("withKnownType", True),
    ):
        check_less_than(
            key,
            current_result["typeCompleteness"]["exportedSymbolCounts"],
            last_result["typeCompleteness"]["exportedSymbolCounts"],
            invert=invert,
        )

    if args.overwrite_file:
        print("Overwriting file")

        # don't care about differences in time taken
        del current_result["time"]
        del current_result["summary"]["timeInSec"]

        # don't fail on version diff so pyright updates can be automerged
        del current_result["version"]

        for key in (
            # don't save path (because that varies between machines)
            "moduleRootDirectory",
            "packageRootDirectory",
            "pyTypedPath",
        ):
            del current_result["typeCompleteness"][key]

        # prune the symbols to only be the name of the symbols with
        # errors, instead of saving a huge file.
        new_symbols: list[dict[str, str]] = []
        for symbol in current_result["typeCompleteness"]["symbols"]:
            if symbol["diagnostics"]:
                # function name + message should be enough context for people!
                new_symbols.extend(
                    {"name": symbol["name"], "message": diagnostic["message"]}
                    for diagnostic in symbol["diagnostics"]
                )
                continue

        # Ensure order of arrays does not affect result.
        new_symbols.sort(key=lambda module: module.get("name", ""))
        current_result["generalDiagnostics"].sort()
        current_result["typeCompleteness"]["modules"].sort(
            key=lambda module: module.get("name", "")
        )

        del current_result["typeCompleteness"]["symbols"]
        current_result["typeCompleteness"]["diagnostics"] = new_symbols

        with open(get_result_file_name(platform), "w") as file:
            json.dump(current_result, file, sort_keys=True, indent=2)
            # add newline at end of file so it's easier to manually modify
            file.write("\n")

    if py_typed_file is not None:
        print("deleting py.typed")
        py_typed_file.unlink()

    print("*" * 20)

    return int(failed)


def main(args: argparse.Namespace) -> int:
    res = 0
    for platform in "Linux", "Windows", "Darwin":
        res += check_type(args, platform)
    return res


parser = argparse.ArgumentParser()
parser.add_argument("--overwrite-file", action="store_true", default=False)
parser.add_argument("--full-diagnostics-file", type=Path, default=None)
args = parser.parse_args()

assert __name__ == "__main__", "This script should be run standalone"
sys.exit(main(args))
