import ast
import sys

import pytest

from trio._tests.pytest_plugin import skip_if_optional_else_raise

# imports in gen_exports that are not in `install_requires` in setup.py
try:
    import astor  # noqa: F401
    import isort  # noqa: F401
except ImportError as error:
    skip_if_optional_else_raise(error)


from trio._tools.gen_exports import (
    File,
    create_passthrough_args,
    get_public_methods,
    process,
    run_linters,
)

SOURCE = '''from _run import _public
from somewhere import Thing

class Test:
    @_public
    def public_func(self):
        """With doc string"""

    @ignore_this
    @_public
    @another_decorator
    async def public_async_func(self) -> Thing:
        pass  # no doc string

    def not_public(self):
        pass

    async def not_public_async(self):
        pass
'''

IMPORT_1 = """\
from somewhere import Thing
"""

IMPORT_2 = """\
from somewhere import Thing
import os
"""

IMPORT_3 = """\
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from somewhere import Thing
"""


def test_get_public_methods():
    methods = list(get_public_methods(ast.parse(SOURCE)))
    assert {m.name for m in methods} == {"public_func", "public_async_func"}


def test_create_pass_through_args():
    testcases = [
        ("def f()", "()"),
        ("def f(one)", "(one)"),
        ("def f(one, two)", "(one, two)"),
        ("def f(one, *args)", "(one, *args)"),
        (
            "def f(one, *args, kw1, kw2=None, **kwargs)",
            "(one, *args, kw1=kw1, kw2=kw2, **kwargs)",
        ),
    ]

    for funcdef, expected in testcases:
        func_node = ast.parse(funcdef + ":\n  pass").body[0]
        assert isinstance(func_node, ast.FunctionDef)
        assert create_passthrough_args(func_node) == expected


skip_lints = pytest.mark.skipif(
    sys.implementation.name != "cpython",
    reason="gen_exports is internal, black/isort only runs on CPython",
)


@skip_lints
@pytest.mark.parametrize("imports", ["", IMPORT_1, IMPORT_2, IMPORT_3])
def test_process(tmp_path, imports):
    try:
        import black  # noqa: F401
    # there's no dedicated CI run that has astor+isort, but lacks black.
    except ImportError as error:  # pragma: no cover
        skip_if_optional_else_raise(error)

    modpath = tmp_path / "_module.py"
    genpath = tmp_path / "_generated_module.py"
    modpath.write_text(SOURCE, encoding="utf-8")
    file = File(modpath, "runner", platform="linux", imports=imports)
    assert not genpath.exists()
    with pytest.raises(SystemExit) as excinfo:
        process([file], do_test=True)
    assert excinfo.value.code == 1
    process([file], do_test=False)
    assert genpath.exists()
    process([file], do_test=True)
    # But if we change the lookup path it notices
    with pytest.raises(SystemExit) as excinfo:
        process(
            [File(modpath, "runner.io_manager", platform="linux", imports=imports)],
            do_test=True,
        )
    assert excinfo.value.code == 1
    # Also if the platform is changed.
    with pytest.raises(SystemExit) as excinfo:
        process([File(modpath, "runner", imports=imports)], do_test=True)
    assert excinfo.value.code == 1


@skip_lints
def test_lint_failure(tmp_path) -> None:
    """Test that processing properly fails if black or ruff does."""
    try:
        import black  # noqa: F401
        import ruff  # noqa: F401
    except ImportError as error:  # pragma: no cover
        skip_if_optional_else_raise(error)

    file = File(tmp_path / "module.py", "module")

    with pytest.raises(SystemExit):
        run_linters(file, "class not valid code ><")

    with pytest.raises(SystemExit):
        run_linters(file, "import waffle\n;import trio")
