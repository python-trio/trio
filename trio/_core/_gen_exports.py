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


def check_obsolete_functions(funcs, meths):
    """ Check if there are functions that are
    not public anymore.
    Return any functions that are not in methods
    """
    return [func for func in funcs if func not in meths]


def check_new_methods(meths, funcs):
    """ Check if there are new methods that are
    public but haven't been exported yet.
    """
    return [meth for meth in meths if meth not in funcs]


def remove_public_function(tree, func):
    """ Remove a public function from a module
    """


def add_public_function(tree, func):
    """ Add a public function from a module
    """


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
    The function walks the given tree and extracs
    all objects that are functions and have an
    attribute of _public set to True.
    Having the attribute is the only criteria,
    so any function having this attribute will be
    exported.
    """
    methods = [
        node for node in ast.walk(tree)
        if is_function(node) and get_doc_string(node).startswith('"""PUBLIC')
    ]
    return methods


def get_gen_tree(module_file):
    """ The function splits the run.py file into
    two parts and returns the ast tree
    of the genereated second part
    """
    with open(RUN_MODULE_FILE, 'r') as module_file:
        module_code = module_file.read()
        gen_code = module_code.split('# yapf: disable')[-1]
    return ast.parse(gen_code)


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


def get_public_functions(tree):
    """ Get all exported functions
    of the genereated tree. No checking
    takes place as the generated tree does not 
    contain any other functions or methods.
    """
    return [func for func in ast.walk(tree) if is_function(func)]


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
    if isinstance(doc, ast.Expr) and hasattr(doc.value, 's'):
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
    methods = [meth[0] for tree in trees for meth in get_public_methods(tree)]

    # Generate an ast tree for the generated part of the file
    gen_tree = get_gen_tree(RUN_MODULE_FILE)

    # Get all currently exported functions
    functions = [f for f in get_public_functions(gen_tree)]

    # Check for obsolete functions

    print([m.name for m in methods])
    print([f.name for f in functions])
    # print([get_doc_string(f) for f in methods])
    print(split_gen_tree(gen_tree))
    print(get_module_trees_by_dir(SOURCE_TREE))


if __name__ == '__main__':
    gen_exports()
