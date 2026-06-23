from __future__ import annotations

import ast
import inspect
import sys
from code import InteractiveConsole
from signal import SIGINT, raise_signal
from types import CodeType, FunctionType

import outcome

import trio
from trio._util import final

try:
    import pyrepl
    from pyrepl import commands, reader as r, readline
except ImportError:
    try:
        import _pyrepl as pyrepl
        from _pyrepl import commands, reader as r, readline
    except ImportError:
        print(
            "Trio's REPL requires CPython 3.13+, PyPy, or installing pyrepl from PyPI."
        )
        exit(1)

# there are differences between the CPython pyrepl and PyPI pyrepl
try:
    # The following expression fails on PyPy, even though you can
    # `import pyrepl`. This is important because PyPy simply vendors
    # CPython pyrepl: https://github.com/pypy/pypy/issues/4990
    pyrepl.__version__  # noqa: B018
except AttributeError:
    CPYTHON_VENDOR = True
else:
    CPYTHON_VENDOR = False


@final
class TrioInteractiveConsole(InteractiveConsole):
    def __init__(  # type: ignore[no-any-unimported]
        self,
        repl_locals: dict[str, object] | None = None,
    ) -> None:
        super().__init__(locals=repl_locals)
        self.compile.compiler.flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT

    def runcode(self, code: CodeType) -> None:
        func = FunctionType(code, self.locals)
        if inspect.iscoroutinefunction(func):
            result = trio.from_thread.run(outcome.acapture, func)
        else:
            result = trio.from_thread.run_sync(outcome.capture, func)
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

        # clear any residual KI
        trio.from_thread.run(trio.lowlevel.checkpoint_if_cancelled)
        # trio.from_thread.check_cancelled() has too long of a memory


async def repl_input(reader: r.Reader | None, prompt: str) -> str:
    assert reader is not None
    reader.ps1 = prompt
    reader.prepare()
    try:
        reader.refresh()
        while not reader.finished:
            if not reader.handle1(block=False):
                if sys.platform == "win32":
                    await trio.lowlevel.wait_readable(pyrepl.windows_console.InHandle)
                else:
                    await trio.lowlevel.wait_readable(reader.console.input_fd)

        if CPYTHON_VENDOR:
            return reader.get_unicode()  # type: ignore[no-any-return]
        else:
            return reader.get_str()  # type: ignore[no-any-return]
    finally:
        reader.restore()


async def run_repl(console: TrioInteractiveConsole, reader: r.Reader | None) -> None:
    # mostly copy-pasted from code.InteractiveConsole.interact
    try:
        sys.ps1  # noqa: B018
    except AttributeError:
        sys.ps1 = ">>> "
    try:
        sys.ps2  # noqa: B018
    except AttributeError:
        sys.ps2 = "... "

    banner = (
        f"trio REPL {sys.version} on {sys.platform}\n"
        f'Use "await" directly instead of "trio.run()".\n'
        f'Type "help", "copyright", "credits" or "license" '
        f"for more information.\n"
        f'{getattr(sys, "ps1", ">>> ")}import trio\n'
    )
    console.write(banner)
    more = 0

    while True:
        try:
            prompt = sys.ps2 if more else sys.ps1
            try:
                line = await repl_input(reader, prompt)
            except EOFError:
                console.write("\n")
                break
            else:
                more = await trio.to_thread.run_sync(console.push, line)
        except KeyboardInterrupt:
            console.write("\nKeyboardInterrupt\n")
            console.resetbuffer()
            more = 0


def main(original_locals: dict[str, object]) -> None:
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

    # This call also registers all necessary signal handlers.
    # Otherwise, we would not be able to run `readline` in a child
    # thread.
    reader = readline._get_reader()

    if not CPYTHON_VENDOR:
        # The default `interrupt` command finishes the console, which
        # adds an extra newline. Unforgivable!
        class interrupt(commands.FinishCommand):  # type: ignore[misc,no-any-unimported]
            def do(self) -> None:
                raise_signal(SIGINT)

        reader.commands["interrupt"] = interrupt

    console = TrioInteractiveConsole(repl_locals)
    trio.run(run_repl, console, reader)
