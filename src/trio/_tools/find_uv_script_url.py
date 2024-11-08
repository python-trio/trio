"""
Script to find the uv script url from a constraints file.

Has only stdlib dependencies because it runs before any package is installed.
"""

from __future__ import annotations

import argparse
import pathlib
import sys


def _url(v: str) -> str:
    return f"https://astral.sh/uv/{v}/install.sh"


def _parse(v: pathlib.Path) -> str:
    with v.open("rb") as f:
        for line in f:
            before, found, version = line.partition(b"uv==")
            if not before and found:
                return _url(version.removesuffix(b"\n").decode("ascii"))
    raise RuntimeError("no version found")


def main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Find the uv version in a requirements.txt",
    )
    parser.add_argument("filename", type=pathlib.Path)
    parsed_args = parser.parse_args(args=args)
    version = _parse(parsed_args.filename)
    print(version)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
