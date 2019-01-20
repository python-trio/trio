import ast
import pytest
import trio

from trio import _core

from gen_exports import is_function, is_public


@pytest.fixture
def setup_ast():
    """ Create a function and async function compiled code 
    """
    source = '''
from _run import _public

def func():
    """"""

async def async_func():
    """"""

class Test():
    def non_public_func():
        """"""

    @_public
    def public_func():
        """"""
    '''
    module = ast.parse(source)
    # for node in ast.walk(module):
    #     if isinstance(node, ast.FunctionDef):
    #         func = node
    #     if isinstance(node, ast.AsyncFunctionDef):
    #         async_func = node
    #     if isinstance(node, ast.FunctionDef) and node.name == 'public_func':
    #         public_func = node

    return module


def test_is_function(setup_ast):
    module = setup_ast
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef):
            assert is_function(node) is True
        if isinstance(node, ast.AsyncFunctionDef):
            assert is_function(node) is True
    assert is_function(module) is False


def test_is_public(setup_ast):
    module = setup_ast
    for node in ast.walk(module):
        if is_function(node) and node.name == 'public_func':
            assert is_public(node) is True
        if is_function(node) and node.name == 'non_public_func':
            assert is_public(node) is False
