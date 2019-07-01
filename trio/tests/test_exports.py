import sys
import importlib
import types

import pytest

import trio
import trio.testing

from .. import _core


def test_core_is_properly_reexported():
    # Each export from _core should be re-exported by exactly one of these
    # three modules:
    sources = [trio, trio.hazmat, trio.testing]
    for symbol in dir(_core):
        if symbol.startswith('_') or symbol == 'tests':
            continue
        found = 0
        for source in sources:
            if (
                symbol in dir(source)
                and getattr(source, symbol) is getattr(_core, symbol)
            ):
                found += 1
        print(symbol, found)
        assert found == 1


def public_namespaces(module):
    yield module.__name__
    for name, value in module.__dict__.items():
        if name.startswith("_"):
            continue
        if not isinstance(value, types.ModuleType):
            continue
        if not value.__name__.startswith(module.__name__):
            continue
        if value is module:
            continue
        # We should rename the trio.tests module (#274), but until then we use
        # a special-case hack:
        if value.__name__ == "trio.tests":
            continue
        yield from public_namespaces(value)


NAMESPACES = list(public_namespaces(trio))


# pylint/jedi often have trouble with alpha releases, where Python's internals
# are in flux, grammar may not have settled down, etc.
@pytest.mark.skipif(
    sys.version_info.releaselevel == "alpha",
    reason="skip static introspection tools on Python dev/alpha releases",
)
@pytest.mark.filterwarnings(
    # https://github.com/PyCQA/astroid/issues/681
    "ignore:the imp module is deprecated.*:DeprecationWarning"
)
@pytest.mark.filterwarnings(
    # Same as above, but on Python 3.5
    "ignore:the imp module is deprecated.*:PendingDeprecationWarning"
)
@pytest.mark.parametrize("modname", NAMESPACES)
@pytest.mark.parametrize("tool", ["pylint", "jedi"])
def test_static_tool_sees_all_symbols(tool, modname):
    module = importlib.import_module(modname)

    def no_underscores(symbols):
        return {symbol for symbol in symbols if not symbol.startswith("_")}

    runtime_names = no_underscores(dir(module))

    # We should rename the trio.tests module (#274), but until then we use a
    # special-case hack:
    if modname == "trio":
        runtime_names.remove("tests")

    if tool == "pylint":
        from pylint.lint import PyLinter
        linter = PyLinter()
        ast = linter.get_ast(module.__file__, modname)
        static_names = no_underscores(ast)
    elif tool == "jedi":
        import jedi
        # Simulate typing "import trio; trio.<TAB>"
        script = jedi.Script("import {}; {}.".format(modname, modname))
        completions = script.completions()
        static_names = no_underscores(c.name for c in completions)
    else:  # pragma: no cover
        assert False

    # It's expected that the static set will contain more names than the
    # runtime set:
    # - static tools are sometimes sloppy and include deleted names
    # - some symbols are platform-specific at runtime, but always show up in
    #   static analysis (e.g. in trio.socket or trio.hazmat)
    # So we check that the runtime names are a subset of the static names.
    missing_names = runtime_names - static_names
    if missing_names:  # pragma: no cover
        print("{} can't see the following names in {}:".format(tool, modname))
        print()
        for name in sorted(missing_names):
            print("    {}".format(name))
        assert False
