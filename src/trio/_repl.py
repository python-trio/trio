from __future__ import annotations

import ast
import contextlib
import ctypes
import inspect
import os
import sys
import types
import warnings
from code import InteractiveConsole

import outcome

import trio
import trio.lowlevel
from trio._util import final


@final
class TrioInteractiveConsole(InteractiveConsole):
    def __init__(self, repl_locals: dict[str, object] | None = None) -> None:
        super().__init__(locals=repl_locals)
        self.code_to_run = None
        self.compile.compiler.flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT

        readline = sys.modules.get("readline")
        if readline is not None:
            self.readline = readline
            if hasattr(readline, "__file__"):
                self.rl = ctypes.CDLL(readline.__file__)
            else:
                self.rl = ctypes.pythonapi
            if hasattr(self.rl, "rl_catch_signals"):
                ctypes.c_int.in_dll(self.rl, "rl_catch_signals").value = 0
            self.rlcallbacktype = ctypes.CFUNCTYPE(None, ctypes.c_char_p)
            self.rl.rl_callback_handler_install.argtypes = [
                ctypes.c_char_p,
                self.rlcallbacktype,
            ]
        else:
            self.rl = None
            self.linebuffer = ""

    def runcode(self, code: types.CodeType) -> None:
        self.code_to_run = code

    async def actually_run_code(self) -> None:
        # https://github.com/python/typeshed/issues/13768
        func = types.FunctionType(self.code_to_run, self.locals)  # type: ignore[arg-type]
        self.code_to_run = None
        if inspect.iscoroutinefunction(func):
            result = await outcome.acapture(func)
        else:
            result = outcome.capture(func)
        if isinstance(result, outcome.Error):
            # If it is SystemExit, quit the repl. Otherwise, print the traceback.
            # If there is a SystemExit inside a BaseExceptionGroup, it probably isn't
            # the user trying to quit the repl, but rather an error in the code. So, we
            # don't try to inspect groups for SystemExit. Instead, we just print and
            # return to the REPL.
            if isinstance(result.error, SystemExit):
                raise result.error
            else:
                # Inline our own version of self.showtraceback that can use
                # outcome.Error.error directly to print clean tracebacks.
                # This also means overriding self.showtraceback does nothing.
                sys.last_type, sys.last_value = type(result.error), result.error
                sys.last_traceback = result.error.__traceback__
                # see https://docs.python.org/3/library/sys.html#sys.last_exc
                if sys.version_info >= (3, 12):
                    sys.last_exc = result.error

                # We always use sys.excepthook, unlike other implementations.
                # This means that overriding self.write also does nothing to tbs.
                sys.excepthook(sys.last_type, sys.last_value, sys.last_traceback)

    async def ainteract(self, banner):
        try:
            sys.ps1
        except AttributeError:
            sys.ps1 = ">>> "
        try:
            sys.ps2
        except AttributeError:
            sys.ps2 = "... "

        self.write("%s\n" % str(banner))
        more = 0

        while True:
            try:
                if more:
                    prompt = sys.ps2
                else:
                    prompt = sys.ps1
                try:
                    line = await self.async_input(prompt)
                except EOFError:
                    self.write("\n")
                    break
                else:
                    more = self.push(line)
                if more == 0:
                    await self.actually_run_code()
            except KeyboardInterrupt:
                self.write("\nKeyboardInterrupt\n")
                self.resetbuffer()
                more = 0

    async def async_input(self, prompt=""):
        if self.rl:
            line = b""

            @self.rlcallbacktype
            def callback(text):
                nonlocal line
                line = text

            try:
                self.rl.rl_callback_handler_install(prompt.encode(), callback)
                while line == b"":
                    await trio.lowlevel.wait_readable(0)
                    self.rl.rl_callback_read_char()
            except KeyboardInterrupt:
                self.rl.rl_free_line_state()
                raise
            finally:
                self.rl.rl_callback_handler_remove()
            if line is None:
                raise EOFError
            self.readline.add_history(line.decode())
            return line.decode()
        else:
            line = ""
            print(prompt, file=sys.stderr, end="")
            sys.stderr.flush()
            while True:
                await trio.lowlevel.wait_readable(0)
                new = os.read(0, 1024).decode()
                if new == "":
                    raise EOFError
                self.linebuffer += new
                line, nl, buffer = self.linebuffer.partition("\n")
                if nl:
                    self.linebuffer = buffer
                    return line
            return line


async def run_repl(console: TrioInteractiveConsole) -> None:
    banner = (
        f"trio REPL {sys.version} on {sys.platform}\n"
        f'Use "await" directly instead of "trio.run()".\n'
        f'Type "help", "copyright", "credits" or "license" '
        f"for more information.\n"
        f'{getattr(sys, "ps1", ">>> ")}import trio'
    )
    try:
        await console.ainteract(banner)
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


if __name__ == "__main__":
    main(locals())
