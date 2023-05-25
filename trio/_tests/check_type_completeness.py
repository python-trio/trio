#!/usr/bin/env python3
import subprocess
import json
from pathlib import Path
from typing import Any
import sys
import argparse

RES_FILE = Path(__file__).parent / "verify_types.json"
failed = False


def run_pyright():
    return subprocess.run(
        ["pyright", "--verifytypes=trio", "--outputjson", "--ignoreexternal"],
        capture_output=True,
    )


def main(args: argparse.Namespace) -> int:
    print("*" * 20, "\nChecking type completeness hasn't gone down...")
    current_dict: dict[str, Any] = {}
    last_dict: dict[str, Any] = {}

    def check_less_than(key, /, invert=False):
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
        if isinstance(current, float):
            current = f"{current:.4}"
            last = f"{last:.4}"
        print(
            f"{key} has gone {'down' if current<last else 'up'} from {last} to {current}"
        )

    def check_zero(key):
        if current_dict[key] != 0:
            global failed
            failed = True
            print(f"ERROR: {key} is {current_dict[key]}")

    res = run_pyright()
    current_result = json.loads(res.stdout)

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

        res = run_pyright()
        current_result = json.loads(res.stdout)

    if res.stderr:
        print(res.stderr)

    last_result = json.loads(RES_FILE.read_text())
    current_dict = current_result["summary"]

    for key in "errorCount", "warningCount", "informationCount":
        check_zero(key)

    current_dict = current_result["typeCompleteness"]
    last_dict = last_result["typeCompleteness"]
    for key in (
        "missingFunctionDocStringCount",
        "missingClassDocStringCount",
        "missingDefaultParamCount",
    ):
        check_less_than(key)
    check_less_than("completenessScore", invert=True)

    current_dict = current_dict["exportedSymbolCounts"]
    last_dict = last_dict["exportedSymbolCounts"]

    for key in "withUnknownType", "withAmbiguousType":
        check_less_than(key)
    check_less_than("withKnownType", invert=True)

    assert (
        res.returncode != 0
    ), "Fully type complete! Replace this script with running pyright --verifytypes directly in CI and checking exit code."

    if args.overwrite_file:
        print("Overwriting file")

        # don't care about differences in time taken
        del current_result["time"]
        del current_result["summary"]["timeInSec"]

        for key in (
            # don't save huge file for now
            "symbols",
            "modules",
            # don't save path
            "moduleRootDirectory",
            "packageRootDirectory",
            "pyTypedPath",
        ):
            del current_result["typeCompleteness"][key]

        with open(RES_FILE, "w") as file:
            json.dump(current_result, file, sort_keys=True, indent=2)

    print("*" * 20)

    return int(failed)


parser = argparse.ArgumentParser()
parser.add_argument("--overwrite-file", action="store_true", default=False)
args = parser.parse_args()

assert __name__ == "__main__", "This script should be run standalone"
sys.exit(main(args))
