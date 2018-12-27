import ast
import astor
import os

RUN_MODULE_FILE = './trio/_core/_run.py'
WINDOWS_MODULE_FILE = './trio/_core/_io_windows.py'
EPOLL_MODULE_FILE = './trio/_core/_io_epoll.py'
KQUEUE_MODULE_FILE = './trio/_core/_io_kqueue.py'
SOURCE_TREE = './trio/_core'
EXPORT_MODULE_FILES = [
    './trio/_core/_run.py', './trio/_core/_io_windows.py',
    './trio/_core/_io_epoll.py', './trio/_core/_io_kqueue.py'
]


def is_function(node):
    """ Check if an ast node is a function
    or async function
    """
    if isinstance(node, ast.FunctionDef) or \
       isinstance(node, ast.AsyncFunctionDef):
        return True
    return False


def get_public_methods(tree):
    """ Return a list of tuples of methods and parents
    marked as public.
    The function walks the given tree and extracts
    all objects that are functions and have a
    doc string that starts with PUBLIC
    """
    methods = [
        node for node in ast.walk(tree)
        if is_function(node) and get_doc_string(node).startswith('PUBLIC')
    ]
    return methods


def split_gen_tree(tree):
    """ Split the tree into four
    sections:
    - Functions available for Windows
    - Functions available for Epoll
    - Functions available for Kqueue
    - Functions general available
    """
    # Get the if blocks which represent Windows, Epoll Kqueue
    ifs = [node for node in ast.walk(tree) if isinstance(node, ast.If)]

    return ifs


def get_module_trees_from_list(module_files):
    """ Converts a list of modules into ast module objects
    """
    module_trees = [
        astor.parse_file(module_file) for module_file in module_files
    ]
    return module_trees


def get_module_trees_by_dir(source_dir):
    """ Converts a list of modules into ast module objects
    """
    return [
        astor.code_to_ast.parse_file(os.path.join(*mod_file))
        for mod_file in astor.code_to_ast.find_py_files(source_dir)
    ]


def get_doc_string(func):
    """ Returns the doc string of a function
    or an empty sting if none
    """
    if not is_function(func):
        raise TypeError("Docstring can only be retrieved for a function")
    doc = func.body[0]
    if isinstance(doc, ast.Expr):
        if hasattr(doc, 'value'):
            if hasattr(doc.value, 's'):
                return doc.value.s
    return ""


def gen_general_exports():
    """ Generates general available functions
    """


def gen_windows_exports():
    """ Generates functions only available on windows
    """


def gen_epoll_exports():
    """ Generates functions only available on osx
    """


def gen_kqueue_exports():
    """ Generates functions only available on linux
    """


def gen_exports():
    """ Sync the existing functions with the list
    of exported functions imported from _public
    """
    # Get all trees we have classes with methods to export in
    trees = [tree for tree in get_module_trees_from_list(EXPORT_MODULE_FILES)]

    # Get all methods we want to export
    methods = [meth for tree in trees for meth in get_public_methods(tree)]

    # print(len(methods))
    [print(m.name, m.args.defaults, m.args.kw_defaults) for m in methods]
    # [print(astor.to_source(m)) for m in methods]
    # print([get_doc_string(f) for f in methods])
    # print(get_module_trees_by_dir(SOURCE_TREE))


if __name__ == '__main__':
    gen_exports()
