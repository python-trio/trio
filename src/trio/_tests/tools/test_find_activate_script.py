import os
import pathlib
import venv

import pytest

from trio._tools import find_activate_script


def test_find_activate_script(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_dir = tmp_path / "venv"
    venv.create(env_dir)
    find_activate_script.main([os.fsdecode(env_dir)])
    captured = capsys.readouterr()
    assert captured.err == ""
    activate = pathlib.Path(captured.out.removesuffix("\n"))
    assert activate.exists()
    assert activate.name == "activate"
