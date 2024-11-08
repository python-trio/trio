"""
Script to find the activate script in a virtual environment.

Has only stdlib dependencies because it runs before any package is installed.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import sysconfig


def _venv_path(env_dir: str, name: str) -> str:
    vars_ = {
        "base": env_dir,
        "platbase": env_dir,
        "installed_base": env_dir,
        "installed_platbase": env_dir,
    }
    return sysconfig.get_path(name, scheme="venv", vars=vars_)


if sys.version_info >= (3, 11):

    def _get_binpath(v: pathlib.Path) -> pathlib.Path:
        return pathlib.Path(_venv_path(env_dir=os.fsdecode(v), name="scripts"))

elif sys.platform == "win32":

    def _get_binpath(v: pathlib.Path) -> pathlib.Path:
        return v / "Scripts"

else:

    def _get_binpath(v: pathlib.Path) -> pathlib.Path:
        return v / "bin"


def _get_activate_script(v: pathlib.Path) -> pathlib.Path:
    return _get_binpath(v) / "activate"


def main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Find the activate script for a given virtual environment",
    )
    parser.add_argument("filename", type=pathlib.Path)
    parsed_args = parser.parse_args(args=args)
    activate = _get_activate_script(parsed_args.filename)
    print(activate)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
