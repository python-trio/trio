from __future__ import annotations

import ast
import contextlib
import inspect
import sys
import types
import warnings
from code import InteractiveConsole
from typing import Generator

import trio
import trio.lowlevel

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup


def _flatten_exception_group(
    excgroup: BaseExceptionGroup[BaseException],
) -> Generator[BaseException, None, None]:
    for exc in excgroup.exceptions:
        if isinstance(exc, BaseExceptionGroup):
            yield from _flatten_exception_group(exc)
        else:
            yield exc


class TrioInteractiveConsole(InteractiveConsole):
    # code.InteractiveInterpreter defines locals as Mapping[str, Any]
    # but when we pass this to FunctionType it expects a dict. So
    # we make the type more specific on our subclass
    locals: dict[str, object]

    def __init__(self, repl_locals: dict[str, object] | None = None):
        super().__init__(locals=repl_locals)
        self.compile.compiler.flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT

    def runcode(self, code: types.CodeType) -> None:
        async def _runcode_in_trio() -> BaseException | None:
            func = types.FunctionType(code, self.locals)
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

        maybe_exc_or_excgroup = trio.from_thread.run(_runcode_in_trio)

        if maybe_exc_or_excgroup is not None:
            # maybe_exc_or_excgroup is an exception, or an exception group.
            # If it is SystemExit or if the exception group contains
            # a SystemExit, quit the repl. Otherwise, print the traceback.
            if isinstance(maybe_exc_or_excgroup, SystemExit):
                raise maybe_exc_or_excgroup
            elif isinstance(maybe_exc_or_excgroup, BaseExceptionGroup):
                sys_exit_exc = maybe_exc_or_excgroup.subgroup(SystemExit)
                if sys_exit_exc:
                    # There is a SystemExit exception, but it might be nested
                    # If there are more than one SystemExit exception in
                    # the group, this will only find and re-raise the first.
                    raise next(_flatten_exception_group(sys_exit_exc))

            # If we didn't raise in either of the conditions above,
            # there was an exception, but no SystemExit. So we raise
            # here and except, so that the console can print the traceback
            # to the user.
            try:
                raise maybe_exc_or_excgroup
            except BaseException:
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
