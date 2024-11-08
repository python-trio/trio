import os
import pathlib

import pytest

from trio._tools import find_uv_script_url


def test_find_uv_script_url(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_bytes(b"# uv==2.0\nuv==1.0\r\n")
    find_uv_script_url.main([os.fsdecode(requirements)])
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == "https://astral.sh/uv/1.0/install.sh\n"


def test_cannot_find_uv_version(tmp_path: pathlib.Path) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_bytes(b"# uv==2\npip==1\n")
    with pytest.raises(RuntimeError, match=r"no version found"):
        find_uv_script_url.main([os.fsdecode(requirements)])
