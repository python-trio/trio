import ast
import astor
import pytest
import os
import sys

from shutil import copyfile
from trio._tools.gen_exports import (
    is_function, is_public, get_public_methods, get_export_modules_by_dir,
    get_module_trees_by_dir, get_doc_string, create_passthrough_args,
    gen_sources, gen_formatted_sources, process_sources, parse_args, IMPORTS,
    YAPF_STYLE
)


@pytest.fixture
def pass_through_source():

    source = '''def func():
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
'''
    return source


@pytest.fixture
def source():
    """ Create a function and async function compiled code 
    """
    source = '''from _run import _public


class Test:

    @_public
    def public_func(self):
        """With doc string"""

    @_public
    async def public_async_func(self):
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

    def non_public_func(self):
        """"""

    def non_pub_func(self):
        """"""
'''
    return non_pub_source


@pytest.fixture
def module(source):
    """Compile the source into an ast module
    """
    return ast.parse(source)


@pytest.fixture
def pass_through_module(pass_through_source):
    """Compile the pass through source into an ast module
    """
    return ast.parse(pass_through_source)


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

@pytest.mark.skipif(sys.version_info >= (3,8),
                    reason="requires on dev version")
def test_get_module_trees_by_dir(mod_path, source, non_pub_source):
    modules = get_module_trees_by_dir(mod_path)
    assert len(modules) == 2
    sources = [astor.to_source(mod) for mod in modules]
    assert source in sources
    assert non_pub_source in sources

@pytest.mark.skipif(sys.version_info >= (3,8),
                    reason="requires on dev version")
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


def test_create_pass_through_args(pass_through_module):
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
    for node in ast.walk(pass_through_module):
        if is_function(node):
            for fnc in test_args.keys():
                if node.name == fnc:
                    assert create_passthrough_args(node) == '({})'.format(
                        test_args[fnc]
                    )

@pytest.mark.skipif(sys.version_info >= (3,8),
                    reason="requires on dev version")
def test_gen_sources_startswith_imports(mod_path):
    sources = gen_sources(mod_path)
    for source in sources.values():
        assert source[0].startswith(IMPORTS)


def test_parse_args():
    parser = parse_args(['-t'])
    assert parser.test is True
    parser = parse_args(['-p'])
    assert parser.path == os.path.join(os.getcwd(), 'trio/_core')
    parser = parse_args([])
    assert parser.test is False and parser.path == os.path.join(
        os.getcwd(), 'trio/_core'
    )
    parser = parse_args(['-p/tmp'])
    assert parser.path == '/tmp'


# def test_process_sources_when_outdated(capsys, real_path, tmp_path):
#     sources = gen_sources(real_path)
#     formatted_sources = gen_formatted_sources(sources)
#     args = parse_args(['-t', '-p {}'.format(tmp_path)])
#     with pytest.raises(SystemExit) as pytest_wrapped_e:
#         process_sources(formatted_sources, args)
#     assert pytest_wrapped_e.type == SystemExit
#     assert pytest_wrapped_e.value.code == -1
#     capture = capsys.readouterr()
#     assert capture.out == 'Source is outdated. Please regenerate.\n'

# def test_process_sources_when_new_and_up_to_date(capsys, real_path, tmpdir):
#     sources = gen_sources(real_path)
#     formatted_sources = gen_formatted_sources(sources)
#     args = parse_args(['-p{}'.format(tmpdir)])
#     process_sources(formatted_sources, args)
#     capture = capsys.readouterr()
#     assert capture.out == 'Sucessfully generated source files at {}\n'.format(
#         tmpdir
#     )
#     args = parse_args(['-t', '-p{}'.format(tmpdir)])
#     process_sources(formatted_sources, args)
#     capture = capsys.readouterr()
#     assert capture.out == 'Source is still up to date\n'
