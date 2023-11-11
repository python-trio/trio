"""Starts an interactive interpreter session that supports top-level
`await`-ing.

To start a new session, run the command:

.. code-block:: shell

   python -m trio

Modeled after the standard library's `asyncio.__main__`. See:

    https://github.com/python/cpython/blob/master/Lib/asyncio/__main__.py
"""
from __future__ import annotations

import ast
import code
import inspect
import sys
import types
from typing import TYPE_CHECKING, Any, TypeVar

import trio

if TYPE_CHECKING:
    from collections.abc import Awaitable, Mapping

T = TypeVar("T")


class TrioInteractiveConsole(code.InteractiveConsole):
    """Interactive Console that will run toplevel awaits in a given nursery"""

    __slots__ = ("nursery",)

    def __init__(
        self, locals_: Mapping[str, Any] | None, nursery: trio.Nursery
    ) -> None:
        super().__init__(locals_)
        self.compile.compiler.flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT
        self.nursery = nursery

    def runcode(self, code: types.CodeType) -> None:
        """Run a code object, and if the return value is a coroutine, wait for it the system nursery."""
        func = types.FunctionType(code, dict(self.locals))

        try:
            result = func()
        except SystemExit:
            raise
        except KeyboardInterrupt:
            self.write("\nKeyboardInterrupt\n")
        except BaseException:
            self.showtraceback()
        else:
            if inspect.iscoroutine(result):
                self.nursery.start_soon(_await, result, self)


async def _await(awaitable: Awaitable[T], console: TrioInteractiveConsole) -> None:
    """Attempt to await an awaitable object and show errors in a given console if they happen."""
    try:
        await awaitable
    except SystemExit:
        raise
    except KeyboardInterrupt:
        console.write("\nKeyboardInterrupt\n")
    except BaseException:
        console.showtraceback()


async def main(repl_locals: dict[str, object]) -> None:
    """Start interactive console with toplevel await support."""
    async with trio.open_nursery() as nursery:
        console = TrioInteractiveConsole(repl_locals, nursery)
        banner = (
            f"Trio {trio.__version__}, "
            f"Python {sys.version} on {sys.platform}\n"
            f'Use "await" directly instead of "trio.run()".\n'
            f'Type "help", "copyright", "credits" or "license" '
            f"for more information.\n"
            f'{getattr(sys, "ps1", ">>> ")}import trio'
        )
        console.interact(banner=banner, exitmsg="exiting Trio REPL...")


def run(locals_: Mapping[str, object]) -> None:
    """Synchronous entry point to start interactive console"""
    repl_locals = {"trio": trio}
    for key in {
        "__name__",
        "__package__",
        "__loader__",
        "__spec__",
        "__builtins__",
        "__file__",
    }:
        repl_locals[key] = locals_[key]

    trio.run(main, repl_locals)


if __name__ == "__main__":
    run(locals())
