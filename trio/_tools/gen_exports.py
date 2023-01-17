#! /usr/bin/env python3
"""
Code generation script for class methods
to be exported as public API
"""
import argparse
import ast
import os
import sys
from pathlib import Path
from textwrap import indent

import astor

PREFIX = "_generated"

HEADER = """# ***********************************************************
# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******
# *************************************************************
from ._run import GLOBAL_RUN_CONTEXT, _NO_SEND
from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED
from ._instrumentation import Instrument

# fmt: off
"""

FOOTER = """# fmt: on
"""

TEMPLATE = """locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
try:
    return{}GLOBAL_RUN_CONTEXT.{}.{}
except AttributeError:
    raise RuntimeError("must be called from async context")
"""


def is_function(node):
    """Check if the AST node is either a function
    or an async function
    """
    if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
        return True
    return False


def is_public(node):
    """Check if the AST node has a _public decorator"""
    if not is_function(node):
        return False
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "_public":
            return True
    return False


def get_public_methods(tree):
    """Return a list of methods marked as public.
    The function walks the given tree and extracts
    all objects that are functions which are marked
    public.
    """
    for node in ast.walk(tree):
        if is_public(node):
            yield node


def create_passthrough_args(funcdef):
    """Given a function definition, create a string that represents taking all
    the arguments from the function, and passing them through to another
    invocation of the same function.

    Example input: ast.parse("def f(a, *, b): ...")
    Example output: "(a, b=b)"
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


def gen_public_wrappers_source(source_path: Path, lookup_path: str) -> str:
    """Scan the given .py file for @_public decorators, and generate wrapper
    functions.

    """
    generated = [HEADER]
    source = astor.code_to_ast.parse_file(source_path)
    for method in get_public_methods(source):
        # Remove self from arguments
        assert method.args.args[0].arg == "self"
        del method.args.args[0]

        # Remove decorators
        method.decorator_list = []

        # Create pass through arguments
        new_args = create_passthrough_args(method)

        # Remove method body without the docstring
        if ast.get_docstring(method) is None:
            del method.body[:]
        else:
            # The first entry is always the docstring
            del method.body[1:]

        # Create the function definition including the body
        func = astor.to_source(method, indent_with=" " * 4)

        # Create export function body
        template = TEMPLATE.format(
            " await " if isinstance(method, ast.AsyncFunctionDef) else " ",
            lookup_path,
            method.name + new_args,
        )

        # Assemble function definition arguments and body
        snippet = func + indent(template, " " * 4)

        # Append the snippet to the corresponding module
        generated.append(snippet)
    generated.append(FOOTER)
    return "\n\n".join(generated)


def matches_disk_files(new_files):
    for new_path, new_source in new_files.items():
        if not os.path.exists(new_path):
            return False
        with open(new_path, encoding="utf-8") as old_file:
            old_source = old_file.read()
        if old_source != new_source:
            return False
    return True


def process(sources_and_lookups, *, do_test):
    new_files = {}
    for source_path, lookup_path in sources_and_lookups:
        print("Scanning:", source_path)
        new_source = gen_public_wrappers_source(source_path, lookup_path)
        dirname, basename = os.path.split(source_path)
        new_path = os.path.join(dirname, PREFIX + basename)
        new_files[new_path] = new_source
    if do_test:
        if not matches_disk_files(new_files):
            print("Generated sources are outdated. Please regenerate.")
            sys.exit(1)
        else:
            print("Generated sources are up to date.")
    else:
        for new_path, new_source in new_files.items():
            with open(new_path, "w", encoding="utf-8") as f:
                f.write(new_source)
        print("Regenerated sources successfully.")


# This is in fact run in CI, but only in the formatting check job, which
# doesn't collect coverage.
def main():  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Generate python code for public api wrappers"
    )
    parser.add_argument(
        "--test", "-t", action="store_true", help="test if code is still up to date"
    )
    parsed_args = parser.parse_args()

    source_root = Path.cwd()
    # Double-check we found the right directory
    assert (source_root / "LICENSE").exists()
    core = source_root / "trio/_core"
    to_wrap = [
        (core / "_run.py", "runner"),
        (core / "_instrumentation.py", "runner.instruments"),
        (core / "_io_windows.py", "runner.io_manager"),
        (core / "_io_epoll.py", "runner.io_manager"),
        (core / "_io_kqueue.py", "runner.io_manager"),
    ]

    process(to_wrap, do_test=parsed_args.test)


if __name__ == "__main__":  # pragma: no cover
    main()
