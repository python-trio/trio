import ast
import astor
import pytest

from tools.gen_exports import (
    is_function, is_public, get_public_methods, get_export_modules_by_dir,
    get_module_trees_by_dir, get_doc_string, create_passthrough_args
)


@pytest.fixture
def source():
    """ Create a function and async function compiled code 
    """
    source = '''from _run import _public


def func():
    """"""


async def async_func():
    """"""


class Test:

    def non_public_func():
        """"""

    def one_arg_func(one):
        """"""

    def two_args_func(one, two):
        """"""

    def var_arg_func(one, *varargs):
        """"""

    def kwonly_arg_func(one, *varargs, kwarg=''):
        """"""

    def kwvar_arg_func(one, **varkwargs):
        """"""

    def all_args_func(one, two, *args, kwargone='', kwargtwo=10, **kwargs):
        """"""

    @_public
    def public_func():
        """With doc string"""

    @_public
    async def public_async_func():
        """"""
'''
    return source


@pytest.fixture
def non_pub_source():
    """ Create a function and async function compiled code 
    """
    non_pub_source = '''def func():
    """"""


async def async_func():
    """"""


class Test:

    def non_public_func():
        """"""

    def non_pub_func():
        """"""
'''
    return non_pub_source


@pytest.fixture
def module(source):
    """Compile the source into an ast module
    """
    return ast.parse(source)


@pytest.fixture
def mod_path(tmp_path, source, non_pub_source):
    mod_path = str(tmp_path.joinpath('public_module.py'))
    with open(mod_path, 'w') as mod_file:
        mod_file.write(source)
    non_pub_mod_path = str(tmp_path.joinpath('non_public_module.py'))
    with open(non_pub_mod_path, 'w') as mod_file:
        mod_file.write(non_pub_source)
    return tmp_path


def test_is_function(module):
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef):
            assert is_function(node) is True
        if isinstance(node, ast.AsyncFunctionDef):
            assert is_function(node) is True
    assert is_function(module) is False


def test_is_public(module):
    for node in ast.walk(module):
        if is_function(node) and node.name == 'public_func':
            assert is_public(node) is True
        if is_function(node) and node.name == 'non_public_func':
            assert is_public(node) is False


def test_get_module_trees_by_dir(mod_path, source, non_pub_source):
    modules = get_module_trees_by_dir(mod_path)
    assert len(modules) == 2
    sources = [astor.to_source(mod) for mod in modules]
    assert source in sources
    assert non_pub_source in sources


def test_get_export_modules_by_dir(mod_path, source):
    modules = get_export_modules_by_dir(mod_path)
    assert len(modules) == 1
    assert source in astor.to_source(modules[0])


def test_get_public_methods(mod_path):
    modules = get_export_modules_by_dir(mod_path)
    methods = get_public_methods(modules[0])
    assert len(methods) == 2
    assert methods[0].name == 'public_func'
    assert methods[1].name == 'public_async_func'


def test_get_doc_string(module):
    for node in ast.walk(module):
        if is_function(node):
            if node.name == 'public_func':
                assert get_doc_string(node) == 'With doc string'
            if node.name == 'public_async_func':
                assert get_doc_string(node) == ''


def test_create_pass_through_args(module):
    test_args = {
        'one_arg_func':
            'one',
        'two_args_func':
            'one, two',
        'var_arg_func':
            'one, *varargs',
        'kwonly_arg_func':
            "one, *varargs, kwarg=kwarg",
        'kwvar_arg_func':
            'one, **varkwargs',
        'all_args_func':
            "one, two, *args, kwargone=kwargone, kwargtwo=kwargtwo, **kwargs"
    }
    for node in ast.walk(module):
        if is_function(node):
            for fnc in test_args.keys():
                if node.name == fnc:
                    assert create_passthrough_args(node) == '({})'.format(
                        test_args[fnc]
                    )
