import io
import subprocess
import sys

import pytest

from trio._tools.mypy_annotate import main, process_line


@pytest.mark.parametrize(
    "platform, src, expected",
    [
        ("Linux", "", ""),
        (
            "Linux",
            "a regular line\n",
            "a regular line\n",
        ),
        (
            "OSX",
            "package\\filename.py:42:8: note: Some info\n",
            "::notice file=package\\filename.py,line=42,col=8,"
            "title=Mypy-OSX::package\\filename.py:(42:8): Some info\n",
        ),
        (
            "Linux",
            "package/filename.py:42:1:46:3: error: Type error here [code]\n",
            "::error file=package/filename.py,line=42,col=1,endLine=46,endColumn=3,"
            "title=Mypy-Linux::package/filename.py:(42:1 - 46:3): Type error here [code]\n",
        ),
        (
            "Windows",
            "package/module.py:87: warn: Bad code\n",
            "::warning file=package/module.py,line=87,"
            "title=Mypy-Windows::package/module.py:87: Bad code\n",
        ),
    ],
    ids=["blank", "normal", "note-wcol", "error-wend", "warn-lineonly"],
)
def test_processing(platform: str, src: str, expected: str) -> None:
    assert process_line(platform, src) == expected


def test_endtoend(monkeypatch, capsys) -> None:
    inp_text = """\
Mypy begun
trio/core.py:15: error: Bad types here [misc]
trio/package/module.py:48:4:56:18: warn: Missing annotations  [no-untyped-def]
Found 3 errors in 29 files
"""
    monkeypatch.setattr(sys, "stdin", io.StringIO(inp_text))

    main("SomePlatform")
    result = capsys.readouterr()
    assert result.err == ""
    assert result.out == (
        "Mypy begun\n"
        "::error file=trio/core.py,line=15,title=Mypy-SomePlatform::trio/core.py:15: Bad types here [misc]\n"
        "::warning file=trio/package/module.py,line=48,col=4,endLine=56,endColumn=18,"
        "title=Mypy-SomePlatform::trio/package/module.py:(48:4 - 56:18): Missing "
        "annotations  [no-untyped-def]\n"
        "Found 3 errors in 29 files\n"
    )
