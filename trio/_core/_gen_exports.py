import ast
import astor
import os
import yapf.yapflib.yapf_api as formatter

SOURCE_TREE = './trio/_core'


def is_function(node):
    return isinstance(node, ast.FunctionDef) \
           or isinstance(node, ast.AsyncFunctionDef)


def is_public(node):
    return is_function(node) \
           and node.decorator_list \
           and isinstance(node.decorator_list[-1], ast.Name) \
           and node.decorator_list[-1].id == '_public'


def get_public_methods(tree):
    """ Return a list of methods marked as public.
    The function walks the given tree and extracts
    all objects that are functions and have a
    doc string that starts with PUBLIC
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


def create_passthrough_args(funcdef):
    """ Create a passthrough arglist
    """
    call_args = []
    for arg in funcdef.args.args:
        call_args.append(arg.arg)
    for _, arg in zip(funcdef.args.defaults[::-1], funcdef.args.args[::-1]):
        call_args.remove(arg.arg)
        call_args.append(arg.arg + "=" + arg.arg)
    if funcdef.args.vararg:
        call_args.append("*" + funcdef.args.vararg.arg)
    for arg in funcdef.args.kwonlyargs:
        call_args.append(arg.arg + "=" + arg.arg)
    if funcdef.args.kwarg:
        call_args.append("**" + funcdef.args.kwarg.arg)
    return "({})".format(", ".join(call_args))


def gen_exports():
    """ Sync the existing functions with the list
    of exported functions imported from _public
    """

    imports = """# ***********************************************************
# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******
# *************************************************************
from ._run import GLOBAL_RUN_CONTEXT, _NO_SEND
from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED


"""
    pub_module_files = set([])
    for module in get_export_modules_by_dir(SOURCE_TREE):
        full_path = os.path.join(
            module.module_path, '_public' + module.module_file
        )
        try:
            os.remove(full_path)
        except FileNotFoundError:
            pass
        with open(full_path, 'w', encoding='utf-8') as pub_file:
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
    for method in methods:
        if method.parent.name == 'Runner':
            ctx = 'runner'
        else:
            ctx = "runner.io_manager"
        # Remove self argument
        method.args.args.pop(0)
        # Remove decorators
        method.decorator_list = []
        # Create passthrough args
        new_args = create_passthrough_args(method)
        # Strip PUBLIC keyword from docs
        doc_string = method.body[0].value.s.replace('PUBLIC ', '')
        method.body[0].value.s = doc_string
        # Remove function body
        del method.body[1:]
        # Create new function body
        template = """locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
try:
    return GLOBAL_RUN_CONTEXT.{}.{}
except AttributeError:
    raise RuntimeError('must be called from async context')
    """.format(ctx, method.name + new_args)
        # Assemble function
        ast_method = ast.parse(template)
        method.body.extend(ast_method.body)
        source = astor.to_source(method).replace('async ', '') + '\n\n'
        pub_file_path = os.path.join(method.module_path, '_public' + method.module_file)
        pub_module_files.add(pub_file_path)
        with open(pub_file_path, 'a', encoding='utf-8') as pub_file:
            pub_file.writelines(source)

    # Fix formatting so yapf won't complain
    for pub_file in pub_module_files:
        formatter.FormatFile(pub_file, in_place=True, style_config='./.style.yapf')


if __name__ == '__main__':
    gen_exports()
