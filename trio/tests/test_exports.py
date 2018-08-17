import trio
import trio.testing

import jedi
<<<<<<< HEAD
import os
import pytest
import sys
=======
>>>>>>> Added tests for pylint and jedi

from pylint.lint import PyLinter

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


def test_pylint_sees_all_non_underscore_symbols_in_namespace():
    # Test pylints ast to contain the same content as dir(trio)
    linter = PyLinter()
    ast_set = set(linter.get_ast(trio.__file__, 'trio'))
    trio_set = set([symbol for symbol in dir(trio) if symbol[0] != '_'])
    trio_set.remove('tests')
    assert trio_set - ast_set == set([])


def test_jedi_sees_all_completions():
    # Test the jedi completion library get all in dir(trio)
    try:
        script = jedi.Script(path=trio.__file__)
        completions = script.completions()
        trio_set = set([symbol for symbol in dir(trio) if symbol[:2] != '__'])
        jedi_set = set([cmp.name for cmp in completions])
        assert trio_set - jedi_set == set([])
    except NotImplementedError:
        pytest.skip("jedi does not yet support {}".format(sys.version))
