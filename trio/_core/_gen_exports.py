import ast
import astor
import os
import textwrap

SOURCE_TREE = './trio/_core'


def get_public_methods(tree):
    """ Return a list of methods marked as public.
    The function walks the given tree and extracts
    all objects that are functions and have a
    doc string that starts with PUBLIC
    """
    methods = []
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            if (isinstance(child, ast.FunctionDef) or
               isinstance(child, ast.AsyncFunctionDef)) and \
               get_doc_string(child).startswith('PUBLIC '):
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
    export_modules = []
    modules = get_module_trees_by_dir(source_dir)

    for module in modules:
        methods = get_public_methods(module)
        if methods:
            export_modules.append(module)
    return export_modules


def get_doc_string(func):
    """ Returns the doc string of a function
    or an empty sting if none
    """
    doc = func.body[0]
    if isinstance(doc, ast.Expr):
        if hasattr(doc, 'value'):
            if hasattr(doc.value, 's'):
                return doc.value.s
    return ""


def gen_exports():
    """ Sync the existing functions with the list
    of exported functions imported from _public
    """

    imports = """from ._run import GLOBAL_RUN_CONTEXT, Runner
from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED


"""

    for module in get_export_modules_by_dir(SOURCE_TREE):
        full_path = os.path.join(
            module.module_path, '_public' + module.module_file
        )
        try:
            os.remove(full_path)
        except FileNotFoundError:
            pass
        with open(full_path, 'w') as pub_file:
            pub_file.writelines(imports)

    # Get all modules we have classes with methods to export in the directory path
    trees = get_export_modules_by_dir(SOURCE_TREE)

    # Get all methods we want to export
    methods = [meth for tree in trees for meth in get_public_methods(tree)]

    # for m in methods:
    #     try:
    #         os.remove(os.path.join(m.module_path, '_public' + m.module_file))
    #     except FileNotFoundError:
    #         pass

    # Get the module and the class of the method as well as the defaults
    for m in methods:
        if m.parent.name == 'Runner':
            ctx = 'runner'
        else:
            ctx = "runner.io_manager"
        # Remove self argument
        m.args.args.pop(0)
        # Remove decorators
        m.decorator_list = []
        # Replace _NO_SEND)
        for default in m.args.defaults:
            if isinstance(default, ast.Name):
                default.id = 'Runner._NO_SEND'
        args = astor.to_source(m.args)
        arg_list = args.split(',')
        new_arg_list = []
        for arg in arg_list:
            if '=' in arg:
                key, value = arg.split('=')
                key = key.strip()
                new_arg_list.append('='.join([key, key]))
            else:
                new_arg_list.append(arg.strip())
        new_args = ', '.join(new_arg_list)
        # Strip PUBLIC keyword from docs
        doc_string = m.body[0].value.s.replace('PUBLIC ', '')
        m.body[0].value.s = doc_string
        # Remove function body
        del m.body[1:]
        # Create new function body
        template = """locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
try:
    return GLOBAL_RUN_CONTEXT.{}.{}
except AttributeError:
    raise RuntimeError('must be called from async context')
    """.format(ctx, m.name + '(' + new_args + ')')
        # Assemble function
        ast_method = ast.parse(template)
        m.body.extend(ast_method.body)
        source = astor.to_source(m).replace('async ', '') + '\n\n'
        with open(os.path.join(m.module_path, '_public' + m.module_file),
                  'a') as pub_file:
            pub_file.writelines(source)


if __name__ == '__main__':
    gen_exports()
