import enum
import importlib
import inspect
import re
import socket as stdlib_socket
import sys
import types
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable

import pytest

import trio
import trio.testing
from trio.tests.conftest import RUN_SLOW

from .. import _core, _util
from .._core.tests.tutil import slow


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
@pytest.mark.parametrize("tool", ["pylint", "jedi", "mypy"])
@pytest.mark.filterwarnings(
    # https://github.com/pypa/setuptools/issues/3274
    "ignore:module 'sre_constants' is deprecated:DeprecationWarning",
)
def test_static_tool_sees_all_symbols(tool, modname, tmpdir):
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
    elif tool == "mypy":
        if not RUN_SLOW:
            pytest.skip("use --run-slow to check against mypy")
        if sys.implementation.name != "cpython":
            pytest.skip("mypy not installed in tests on pypy")

        # create py.typed file
        (Path(trio.__file__).parent / "py.typed").write_text("")

        # mypy behaves strangely when passed a huge semicolon-separated line with `-c`
        # so we use a tmpfile
        tmpfile = tmpdir / "check_mypy.py"
        tmpfile.write_text(
            f"import {modname}\n"
            + "".join(f"{modname}.{name}\n" for name in runtime_names),
            encoding="utf8",
        )
        from mypy.api import run

        res = run(["--config-file=", "--follow-imports=silent", str(tmpfile)])

        # check that there were no errors (exit code 0), otherwise print the errors
        assert res[2] == 0, res[0]
        return
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


# this could be sped up by only invoking mypy once per module, or even once for all
# modules, instead of once per class.
@slow
# see commend on test_static_tool_sees_all_symbols
@pytest.mark.redistributors_should_skip
# pylint/jedi often have trouble with alpha releases, where Python's internals
# are in flux, grammar may not have settled down, etc.
@pytest.mark.skipif(
    sys.version_info.releaselevel == "alpha",
    reason="skip static introspection tools on Python dev/alpha releases",
)
@pytest.mark.parametrize("module_name", PUBLIC_MODULE_NAMES)
@pytest.mark.parametrize("tool", ["jedi", "mypy"])
def test_static_tool_sees_class_members(tool, module_name, tmpdir) -> None:
    module = PUBLIC_MODULES[PUBLIC_MODULE_NAMES.index(module_name)]

    # ignore hidden, but not dunder, symbols
    def no_hidden(symbols):
        return {
            symbol
            for symbol in symbols
            if (not symbol.startswith("_")) or symbol.startswith("__")
        }

    if tool == "mypy":
        if sys.implementation.name != "cpython":
            pytest.skip("mypy not installed in tests on pypy")
        # create py.typed file
        (Path(trio.__file__).parent / "py.typed").write_text("")

    errors: dict[str, Any] = {}
    if module_name == "trio.tests":
        return
    for class_name, class_ in module.__dict__.items():
        if not isinstance(class_, type):
            continue
        if module_name == "trio.socket" and class_name in dir(stdlib_socket):
            continue
        # Deprecated classes are exported with a leading underscore
        if class_name.startswith("_"):  # pragma: no cover
            continue

        # dir() and inspect.getmembers doesn't display properties from the metaclass
        # also ignore some dunder methods that tend to differ but are of no consequence
        ignore_names = set(dir(type(class_))) | {
            "__annotations__",
            "__attrs_attrs__",
            "__attrs_own_setattr__",
            "__class_getitem__",
            "__getstate__",
            "__match_args__",
            "__order__",
            "__orig_bases__",
            "__parameters__",
            "__setstate__",
            "__slots__",
            "__weakref__",
        }

        # pypy seems to have some additional dunders that differ
        if sys.implementation.name == "pypy":
            ignore_names |= {
                "__basicsize__",
                "__dictoffset__",
                "__itemsize__",
                "__sizeof__",
                "__weakrefoffset__",
                "__unicode__",
            }

        # inspect.getmembers sees `name` and `value` in Enums, otherwise
        # it behaves the same way as `dir`
        # runtime_names = no_underscores(dir(class_))
        runtime_names = (
            no_hidden(x[0] for x in inspect.getmembers(class_)) - ignore_names
        )

        if tool == "jedi":
            import jedi

            script = jedi.Script(
                f"from {module_name} import {class_name}; {class_name}."
            )
            completions = script.complete()
            static_names = no_hidden(c.name for c in completions) - ignore_names

            missing = runtime_names - static_names
            extra = static_names - runtime_names
            if BaseException in class_.__mro__ and sys.version_info > (3, 11):
                missing.remove("add_note")

            # TODO: why is this? Is it a problem?
            if class_ == trio.StapledStream:
                extra.remove("receive_stream")
                extra.remove("send_stream")

            if missing | extra:
                errors[f"{module_name}.{class_name}"] = {
                    "missing": missing,
                    "extra": extra,
                }
        elif tool == "mypy":
            tmpfile = tmpdir / "check_mypy.py"
            sorted_runtime_names = list(sorted(runtime_names))
            content = f"from {module_name} import {class_name}\n" + "".join(
                f"{class_name}.{name}\n" for name in sorted_runtime_names
            )
            tmpfile.write_text(content, encoding="utf8")
            from mypy.api import run

            res = run(
                [
                    "--config-file=",
                    "--follow-imports=silent",
                    "--disable-error-code=operator",
                    str(tmpfile),
                ]
            )
            if res[2] != 0:
                print(res)
                it = iter(res[0].split("\n")[:-2])
                for output_line in it:
                    # hack to get around windows path starting with <drive>:<path>
                    output_line = output_line[2:]

                    _, line, error_type, message = output_line.split(":")

                    # -2 due to lines being 1-indexed and to skip the import line
                    symbol = (
                        f"{module_name}.{class_name}."
                        + sorted_runtime_names[int(line) - 2]
                    )

                    # The POSIX-only attributes get listed in `dir(trio.Path)` since
                    # they're in `dir(pathlib.Path)` on win32 cpython. This should *maybe*
                    # be fixed in the future, but for now we ignore it.
                    if (
                        symbol
                        in ("trio.Path.group", "trio.Path.owner", "trio.Path.is_mount")
                        and sys.platform == "win32"
                        and sys.implementation.name == "cpython"
                    ):
                        continue

                    # a bunch of symbols have this error, e.g. trio.lowlevel.Task.context
                    # but I don't think that's a problem - and if it is it would likely
                    # be picked up by "proper" mypy tests elsewhere
                    if "conflicts with class variable access" in message:
                        continue

                    errors[symbol] = error_type + ":" + message

        else:  # pragma: no cover
            assert False

    if errors:  # pragma: no cover
        from pprint import pprint

        print(f"\n{tool} can't see the following symbols in {module_name}:")
        pprint(errors)
    assert not errors


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
