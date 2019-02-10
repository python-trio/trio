#! /usr/bin/env python3
# -*- coding: utf-8 -`-
"""
Code generation script for class methods
to be exported as public API
"""
import argparse
import ast
import astor
import difflib
import os
import sys
import yapf.yapflib.yapf_api as formatter

from textwrap import indent

SOURCE_TREE = os.path.join(os.getcwd(), 'trio/_core')
YAPF_STYLE = os.path.join(os.getcwd(), '.style.yapf')
PREFIX = '_generated'

IMPORTS = """# ***********************************************************
# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******
# *************************************************************
from ._run import GLOBAL_RUN_CONTEXT, _NO_SEND
from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED

    
"""

TEMPLATE = """locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
try:
    return {} GLOBAL_RUN_CONTEXT.{}.{}
except AttributeError:
    raise RuntimeError('must be called from async context')
"""


def is_function(node):
    """Check if the AST node is either a function
    or an async function
    """
    if isinstance(node, ast.FunctionDef) or \
       isinstance(node, ast.AsyncFunctionDef):
        return True
    return False


def is_public(node):
    """Check if the AST node has a _public decorator
    """
    if is_function(node) and node.decorator_list and \
       isinstance(node.decorator_list[-1], ast.Name) and \
       node.decorator_list[-1].id == '_public':
        return True
    return False


def get_public_methods(tree):
    """ Return a list of methods marked as public.
    The function walks the given tree and extracts
    all objects that are functions which are marked
    public.
    """
    methods = []
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            if is_public(child):
                child.parent = node
                child.module_file = tree.module_file
                child.module_path = tree.module_path
                methods.append(child)
    return methods


def get_module_trees_by_dir(source_dir):
    """ Converts a list of modules into ast module objects
    """
    mod_files = astor.code_to_ast.find_py_files(source_dir)
    modules = []
    for mod_file in mod_files:
        if not mod_file[1].startswith('_public'):
            module = astor.code_to_ast.parse_file(os.path.join(*mod_file))
            module.module_path = mod_file[0]
            module.module_file = mod_file[1]
            modules.append(module)
    return modules


def get_export_modules_by_dir(source_dir):
    """Return all modules in the given directory
    and its sub directories which contain methods
    marked to be public as AST module trees
    """
    export_modules = []
    modules = get_module_trees_by_dir(source_dir)

    for module in modules:
        methods = get_public_methods(module)
        if methods:
            export_modules.append(module)
    return export_modules


def get_doc_string(func):
    """ Returns the doc string of a function
    or None if no doc string is present
    """
    try:
        return ast.get_docstring(func)
    except TypeError:
        return


def create_passthrough_args(funcdef):
    """ Create a pass through argument list
    so no arguements are lost
    """
    call_args = []
    for arg in funcdef.args.args:
        call_args.append(arg.arg)
    if funcdef.args.vararg:
        call_args.append("*" + funcdef.args.vararg.arg)
    for arg in funcdef.args.kwonlyargs:
        call_args.append(arg.arg + "=" + arg.arg)
    if funcdef.args.kwarg:
        call_args.append("**" + funcdef.args.kwarg.arg)
    return "({})".format(", ".join(call_args))


def gen_sources(source_tree=None):
    """ Create a source file for each module that contains
    a method that is exported as public API. For each method
    a wrapper is created and added to its corresponding module.
    """
    if source_tree is None:
        source_tree = SOURCE_TREE

    sources = dict()
    # Start each module with a common import code
    # and a warning that is is generated code and will be overwritten
    # on regeneration
    for module in get_export_modules_by_dir(source_tree):
        sources[module.module_file] = [IMPORTS]

    # Get all modules we have classes with methods to export in the directory path
    trees = get_export_modules_by_dir(source_tree)

    # Get all methods we want to export
    methods = [meth for tree in trees for meth in get_public_methods(tree)]

    # Loop over all methods and create the source
    for method in methods:
        if method.parent.name == 'Runner':
            ctx = 'runner'
        else:
            ctx = "runner.io_manager"
        # Remove self from arguments
        method.args.args.pop(0)

        # Remove decorators
        method.decorator_list = []

        # Create pass through arguments
        new_args = create_passthrough_args(method)

        # Remove method body without the docstring
        if get_doc_string(method) is None:
            del method.body[:]
        else:
            # The first entry is always the docstring
            del method.body[1:]

        # Create the function definition including the body
        func = astor.to_source(method, indent_with=' ' * 4)

        # Create export function body
        template = TEMPLATE.format(
            'await' if isinstance(method, ast.AsyncFunctionDef) else '', ctx,
            method.name + new_args
        )

        # Assemble function definition arguments and body
        snippet = func + indent(template, ' ' * 4)

        # Append the snippet to the corresponding module
        sources[method.module_file].append(snippet)
    return sources


def gen_formatted_sources(sources, style_config=YAPF_STYLE):
    formatted_sources = dict()
    # Fix formatting so yapf won't complain
    for pub_file in sources.keys():
        formatted_sources[pub_file], _ = formatter.FormatCode(
            '\n'.join(sources[pub_file]), style_config=style_config
        )
    return formatted_sources


def parse_args(args):
    parser = argparse.ArgumentParser(
        description='Generate python code for public api wrappers'
    )
    parser.add_argument(
        '--path',
        '-p',
        default=SOURCE_TREE,
        type=str,
        const=SOURCE_TREE,
        nargs='?',
        help='create new code at the path (default: {})'.format(SOURCE_TREE)
    )
    parser.add_argument(
        '--test',
        '-t',
        action='store_true',
        help='test if code is still up to date'
    )

    parsed_args = parser.parse_args(args)
    return parsed_args


def process_sources(sources, args):
    ''' Parse the arguments and loop over all sources
    for each given argument comparing and regenerating
    depending on arguments
    '''

    # Loop over all sources and test if the current generated source
    # is still up to date
    if args.test:
        for src in sources:
            pub_file_path = os.path.join(args.path, PREFIX + src)

            try:
                if not os.path.exists(pub_file_path):
                    assert False
                with open(pub_file_path, 'r') as pub_file:
                    old_src = ''.join(pub_file.readlines())
                assert sources[src] == old_src
            except AssertionError:
                print('Source is outdated. Please regenerate.')
                sys.exit(-1)
        else:
            print('Source is still up to date')
            return

    # Test if the given path actually exists and then loop over
    # all sources and generate a new source
    if args.path:
        if not os.path.exists(args.path):
            raise OSError("""Path {} does not exist""".format(args.path))
        for src in sources:
            pub_file_path = os.path.join(args.path, PREFIX + src)
            with open(pub_file_path, 'w', encoding='utf-8') as pub_file:
                pub_file.writelines(sources[src])
        print('Sucessfully generated source files at {}'.format(args.path))


if __name__ == '__main__':
    sources = gen_sources(SOURCE_TREE)
    formatted_sources = gen_formatted_sources(sources)
    args = parse_args(sys.argv[1:])
    process_sources(formatted_sources, args)
