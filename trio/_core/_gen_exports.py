import ast
import astor
import os
import select

RUN_MODULE_FILE = './trio/_core/_run.py'
WINDOWS_MODULE_FILE = './trio/_core/_io_windows.py'
EPOLL_MODULE_FILE = './trio/_core/_io_epoll.py'
KQUEUE_MODULE_FILE = './trio/_core/_io_kqueue.py'
SOURCE_TREE = './trio/_core'

# Both types are needed
FUNCTIONS = [ast.FunctionDef, ast.AsyncFunctionDef]

from ._public import EXPORT_FUNCTIONS, EXPORT_MODULE_FILES


def _check_public_function(module, fn_name):
    """ Parses the module and checks if a function
    with the given name exists
    """


def _remove_public_function(module, fn_name):
    """ Remove a public function from a module
    """


def _add_public_function(module, fn_name):
    """ Add a public function from a module
    """


def _get_export_methods(tree):
    """ Return a list of all functions
    decorated as public
    """
    meths = [
        child for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
        if isinstance(child, ast.FunctionDef)
        and isinstance(parent, ast.ClassDef) and child.name in EXPORTS
    ]
    return meths


def _get_export_functions(tree):
    """ Get all top level functions
    of the tree
    """
    funcs = [
        child for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
        if isinstance(child, ast.FunctionDef)
        and not isinstance(parent, ast.ClassDef)
    ]
    return funcs


def _get_module_trees(module_files):
    """ Converts a list of modules into ast module objects
    """
    # module_files = [
    #     mod for mod in astor.code_to_ast.find_py_files(SOURCE_TREE)
    # ]
    module_trees = [
        astor.parse_file(module_file) for module_file in module_files
    ]
    return module_trees


def _gen_general_exports():
    """ Generates general available functions
    """


def _gen_windows_exports():
    """ Generates functions only available on windows
    """


def _gen_epoll_exports():
    """ Generates functions only available on osx
    """


def _gen_kqueue_exports():
    """ Generates functions only available on linux
    """


def gen_exports():
    """ Sync the existing functions with the list
    of exported functions imported from _public
    """


if __name__ == '__main__':
    gen_exports()

t = [tree for tree in _get_module_trees(EXPORT_MODULE_FILES)]

m = [
    meth.name for tree in _get_module_trees(EXPORT_MODULE_FILES)
    for meth in _get_export_methods(tree)
]

f = [
    f.name for f in _get_export_functions(astor.parse_file(RUN_MODULE_FILE))
    if f.name in EXPORT_FUNCTIONS
]

print(sorted(m))
print(sorted(f))
