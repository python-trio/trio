"""
Checker for various async/await syntax, in the context of Trio.

Included checks:
    * missing-await (e.g. "await async_func()")

Detection is subject to the type inference limitations of the astroid library.

Async-for case is covered by the standard "not-an-iterable" check.

Async-with case is covered by the standard "not-context-manager" check,
assuming no anti-pattern such as __enter__/__exit__ with NotImplementedError.

See  http://pylint.pycqa.org/en/latest/how_tos/custom_checkers.html
and pylint typecheck.py for hints on implementing checkers.

# TODO: name this more generally (pylint-awaitables)
"""

import astroid
from pylint.checkers import BaseChecker
from pylint.interfaces import IAstroidChecker


def register(linter):
    linter.register_checker(MissingAwaitChecker(linter))


def has_yield(node):
    return any(node.nodes_of_class(astroid.Yield)) or \
           any(node.nodes_of_class(astroid.YieldFrom))


class MissingAwaitChecker(BaseChecker):
    __implements__ = IAstroidChecker

    name = "missing-await"
    priority = -1
    msgs = {
        'W5680':
            (
                "Called an async function without immediate 'await'.",
                # TODO: narrow scope to "trio-missing-await"?  Other projects
                # will certainly have missing-await-ish things.
                "missing-await",
                "According to the style of the Trio async I/O library, awaitables "
                "returned from an async function call should be immediately consumed "
                "by 'await'.",
            ),
    }
    options = ()

    def __init__(self, *args, **kwargs):
        super(MissingAwaitChecker, self).__init__(*args, **kwargs)
        self._last_awaited_funcs = None

    def visit_await(self, node):
        # print('** await', node.value)
        if hasattr(node.value, 'func'):
            self._last_awaited_funcs = [node.value.func]

    def visit_asyncwith(self, node):
        # print('** async with', node)
        self._last_awaited_funcs = [item[0] for item in node.items]

    def visit_asyncfor(self, node):
        # print('** async for', node)
        # self._last_awaited_funcs = [item[0] for item in node.items]
        self._last_awaited_funcs = []  # how to resolve?

    def visit_call(self, call_node):
        # print(call_node)
        nodes = [call_node]
        while nodes:
            node = nodes.pop()
            try:
                if isinstance(node, astroid.AsyncFunctionDef):
                    if not has_yield(node) and \
                            self._last_awaited_funcs is None:
                        # or call_node.func not in self._last_awaited_funcs):
                        self.add_message('missing-await', node=call_node)
                        break
                elif isinstance(node, astroid.Call):
                    nodes += node.func.inferred()
                elif isinstance(node, astroid.BoundMethod):
                    nodes += node.inferred()
            except astroid.InferenceError:
                continue
        self._last_awaited_funcs = None
