import ast
import contextlib
import inspect
import sys
import warnings
from code import InteractiveConsole

import trio
import trio.lowlevel


class TrioInteractiveConsole(InteractiveConsole):
    def __init__(self, repl_locals=None):
        super().__init__(repl_locals)
        self.compile.compiler.flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT

    def runcode(self, code):
        async def _runcode_in_trio():
            try:
                coro = eval(code, self.locals)
            except BaseException as e:
                return e

            if inspect.iscoroutine(coro):
                try:
                    await coro
                except BaseException as e:
                    return e
            return None

        e = trio.from_thread.run(_runcode_in_trio)

        if e is not None:
            try:
                raise e
            except SystemExit:
                raise
            except BaseException:  # Only SystemExit should quit the repl
                self.showtraceback()

    async def task(self, repl_func):
        await trio.to_thread.run_sync(repl_func, self)


def run_repl(console):
    banner = (
        f"trio REPL {sys.version} on {sys.platform}\n"
        f'Use "await" directly instead of "trio.run()".\n'
        f'Type "help", "copyright", "credits" or "license" '
        f"for more information.\n"
        f'{getattr(sys, "ps1", ">>> ")}import trio'
    )
    try:
        console.interact(banner=banner)
    finally:
        warnings.filterwarnings(
            "ignore",
            message=r"^coroutine .* was never awaited$",
            category=RuntimeWarning,
        )


def main(original_locals):
    with contextlib.suppress(ImportError):
        import readline  # noqa: F401

    repl_locals = {"trio": trio}
    for key in {
        "__name__",
        "__package__",
        "__loader__",
        "__spec__",
        "__builtins__",
        "__file__",
    }:
        repl_locals[key] = original_locals[key]

    console = TrioInteractiveConsole(repl_locals)
    trio.run(console.task, run_repl)
