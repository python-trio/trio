from __future__ import annotations

import ast
import contextlib
import inspect
import sys
import types
import typing
import warnings
from code import InteractiveConsole
from typing import Dict

import trio
import trio.lowlevel


class TrioInteractiveConsole(InteractiveConsole):
    def __init__(self, repl_locals: dict[str, object] | None = None):
        super().__init__(locals=repl_locals)
        self.compile.compiler.flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT

    def runcode(self, code: types.CodeType) -> None:
        async def _runcode_in_trio() -> BaseException | None:
            # code.InteractiveInterpreter defines locals as Mapping[str, Any]
            # However FunctionType expects a dict. We know our copy of
            # locals will be a dict due to the annotation on repl_locals in __init__
            # so the cast is safe.
            # In addition, we need to use typing.Dict here, because this is _not_ an
            # annotation, so from __future__ import annotations doesn't help.
            func = types.FunctionType(code, typing.cast(Dict[str, object], self.locals))
            try:
                coro = func()
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


async def run_repl(console: TrioInteractiveConsole) -> None:
    banner = (
        f"trio REPL {sys.version} on {sys.platform}\n"
        f'Use "await" directly instead of "trio.run()".\n'
        f'Type "help", "copyright", "credits" or "license" '
        f"for more information.\n"
        f'{getattr(sys, "ps1", ">>> ")}import trio'
    )
    try:
        await trio.to_thread.run_sync(console.interact, banner)
    finally:
        warnings.filterwarnings(
            "ignore",
            message=r"^coroutine .* was never awaited$",
            category=RuntimeWarning,
        )


def main(original_locals: dict[str, object]) -> None:
    with contextlib.suppress(ImportError):
        import readline  # noqa: F401

    repl_locals: dict[str, object] = {"trio": trio}
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
    trio.run(run_repl, console)
