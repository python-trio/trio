import re
import sys
import importlib
import types
import inspect
import enum

import pytest

import trio
import trio.testing
from typing import Iterable

from .. import _core
from .. import _util


def test_core_is_properly_reexported():
    # Each export from _core should be re-exported by exactly one of these
    # three modules:
    sources = [trio, trio.lowlevel, trio.testing]
    for symbol in dir(_core):
        if symbol.startswith("_") or symbol == "tests":
            continue
        found = 0
        for source in sources:
            if symbol in dir(source) and getattr(source, symbol) is getattr(
                _core, symbol
            ):
                found += 1
        print(symbol, found)
        assert found == 1


def public_modules(module):
    yield module
    for name, class_ in module.__dict__.items():
        if name.startswith("_"):  # pragma: no cover
            continue
        if not isinstance(class_, types.ModuleType):
            continue
        if not class_.__name__.startswith(module.__name__):  # pragma: no cover
            continue
        if class_ is module:
            continue
        # We should rename the trio.tests module (#274), but until then we use
        # a special-case hack:
        if class_.__name__ == "trio.tests":
            continue
        yield from public_modules(class_)


PUBLIC_MODULES = list(public_modules(trio))
PUBLIC_MODULE_NAMES = [m.__name__ for m in PUBLIC_MODULES]


# It doesn't make sense for downstream redistributors to run this test, since
# they might be using a newer version of Python with additional symbols which
# won't be reflected in trio.socket, and this shouldn't cause downstream test
# runs to start failing.
@pytest.mark.redistributors_should_skip
# pylint/jedi often have trouble with alpha releases, where Python's internals
# are in flux, grammar may not have settled down, etc.
@pytest.mark.skipif(
    sys.version_info.releaselevel == "alpha",
    reason="skip static introspection tools on Python dev/alpha releases",
)
@pytest.mark.parametrize("modname", PUBLIC_MODULE_NAMES)
@pytest.mark.parametrize("tool", ["pylint", "jedi", "pyright_verifytypes"])
@pytest.mark.filterwarnings(
    # https://github.com/pypa/setuptools/issues/3274
    "ignore:module 'sre_constants' is deprecated:DeprecationWarning",
)
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
        script = jedi.Script(f"import {modname}; {modname}.")
        completions = script.complete()
        static_names = no_underscores(c.name for c in completions)

    elif tool == "pyright_verifytypes":
        import subprocess
        # TODO: create py.typed file

        res = subprocess.run(
            ["pyright", f"--verifytypes={modname}", "--verbose"], capture_output=True
        )
        start_index = res.stdout.find(b"Public modules: ")
        end_index = res.stdout.find(b"Other referenced symbols: ", start_index)
        assert start_index != -1
        assert end_index != -1
        static_names = set(
            x.strip().decode()[len(modname) + 1 :]
            for x in res.stdout[start_index:end_index].split(b"\n")
            if modname + "." in x.decode()
        )

        # don't require verifytypes to see reexported constants from socket
        if modname == "trio.socket":
            import socket

            static_names |= set(filter(str.isupper, dir(socket))) & runtime_names

    else:  # pragma: no cover
        assert False

    # It's expected that the static set will contain more names than the
    # runtime set:
    # - static tools are sometimes sloppy and include deleted names
    # - some symbols are platform-specific at runtime, but always show up in
    #   static analysis (e.g. in trio.socket or trio.lowlevel)
    # So we check that the runtime names are a subset of the static names.
    missing_names = runtime_names - static_names
    if missing_names:  # pragma: no cover
        print(f"{tool} can't see the following names in {modname}:")
        print()
        for name in sorted(missing_names):
            print(f"    {name}")
        assert False


def test_classes_are_final():
    for module in PUBLIC_MODULES:
        for name, class_ in module.__dict__.items():
            if not isinstance(class_, type):
                continue
            # Deprecated classes are exported with a leading underscore
            if name.startswith("_"):  # pragma: no cover
                continue

            # Abstract classes can be subclassed, because that's the whole
            # point of ABCs
            if inspect.isabstract(class_):
                continue
            # Exceptions are allowed to be subclassed, because exception
            # subclassing isn't used to inherit behavior.
            if issubclass(class_, BaseException):
                continue
            # These are classes that are conceptually abstract, but
            # inspect.isabstract returns False for boring reasons.
            if class_ in {trio.abc.Instrument, trio.socket.SocketType}:
                continue
            # Enums have their own metaclass, so we can't use our metaclasses.
            # And I don't think there's a lot of risk from people subclassing
            # enums...
            if issubclass(class_, enum.Enum):
                continue
            # ... insert other special cases here ...

            assert isinstance(class_, _util.Final)
