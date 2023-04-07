#!/usr/bin/env python3
import subprocess
import json
from pathlib import Path
from typing import Any
import sys
import argparse

RES_FILE = Path(__file__).parent / "verify_types.json"


def main(args: argparse.Namespace) -> int:
    print("*" * 20, "\nChecking type completeness hasn't gone down...")
    failed = False
    current_dict: dict[str, Any] = {}
    last_dict: dict[str, Any] = {}

    def check_less_than(key, /, invert=False):
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
            lhs = f"{current:.4}"
            last = f"{last:.4}"
        print(
            f"{key} has gone {'down' if current<last else 'up'} from {last} to {current}"
        )

    def check_zero(key):
        if current_dict[key] != 0:
            failed = True
            print(f"error: {key} is {current_dict[key]})")

    res = subprocess.run(
        ["pyright", "--verifytypes=trio", "--outputjson"], capture_output=True
    )
    if res.stderr:
        print(res.stderr)

    current_result = json.loads(res.stdout)
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
        RES_FILE.write_bytes(res.stdout)

    print("*" * 20)

    return int(failed)


parser = argparse.ArgumentParser()
parser.add_argument("--overwrite-file", action="store_true", default=False)
args = parser.parse_args()

assert __name__ == "__main__", "This script should be run standalone"
sys.exit(main(args))
