from __future__ import annotations

import io
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from trio._tests.pytest_plugin import maybe_ignore_import_error

try:
    from sphinx.application import Sphinx
    from sphinx.util.docutils import docutils_namespace
    from sphinx.util.tags import Tags
except ImportError as error:
    maybe_ignore_import_error(error)


@pytest.mark.parametrize(
    ("fragment", "warning"),
    [
        ("See :ref:`existing-target`.\n", None),
        ("See :ref:`missing-target`.\n", "undefined label"),
        (".. nonexistent-directive::\n", "Unknown directive type"),
        (None, None),
    ],
)
def test_check_newsfragments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fragment: str | None,
    warning: str | None,
) -> None:
    source = tmp_path / "docs" / "source"
    source.mkdir(parents=True)
    fragments = tmp_path / "newsfragments"
    fragments.mkdir()
    if fragment is not None:
        (fragments / "123.bugfix.rst").write_text(fragment, encoding="utf8")
    # The README isn't a fragment and must not be included.
    (fragments / "README.rst").write_text(".. invalid-directive::\n", encoding="utf8")
    (source / "history.rst").write_text(
        "Existing history\n================\n", encoding="utf8"
    )
    (source / "index.rst").write_text(
        ".. _existing-target:\n\nIndex\n=====\n\n.. toctree::\n\n   history\n",
        encoding="utf8",
    )
    (source / "conf.py").write_text("nitpicky = True\n", encoding="utf8")
    originals = {path: path.read_bytes() for path in tmp_path.rglob("*.rst")}
    config_file = Path(__file__).parents[4] / "docs" / "source" / "conf.py"

    if not config_file.is_file():
        # CI runs the installed package tests from the checkout's empty/ directory.
        config_file = Path.cwd().parent / "docs" / "source" / "conf.py"
    if not config_file.is_file():
        pytest.skip("The documentation sources are not installed")

    def forbid_subprocess(*args: object, **kwargs: object) -> None:
        pytest.fail("Checking newsfragments must not run Towncrier or Git")

    with monkeypatch.context() as patch:
        patch.chdir(source)
        patch.setattr(sys, "path", sys.path.copy())
        patch.setenv("SPHINX_AUTODOC_RELOAD_MODULES", "0")
        patch.setattr(subprocess, "run", forbid_subprocess)
        config = runpy.run_path(
            str(config_file),
            init_globals={"tags": Tags(["check-newsfragments"])},
        )

    warnings = io.StringIO()
    with docutils_namespace():
        app = Sphinx(
            str(source),
            str(source),
            str(tmp_path / "build"),
            str(tmp_path / "doctrees"),
            "dummy",
            status=io.StringIO(),
            warning=warnings,
            warningiserror=True,
        )
        app.connect("source-read", config["on_read_source"])
        app.build()
    if warning is None:
        assert app.statuscode == 0, warnings.getvalue()
    else:
        assert app.statuscode == 1
        assert warning in warnings.getvalue()
        assert "123.bugfix.rst:1:" in warnings.getvalue()
    assert originals == {path: path.read_bytes() for path in originals}
