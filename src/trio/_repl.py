from __future__ import annotations

import ast
import inspect
import sys
import warnings
from code import InteractiveConsole
from signal import SIGINT, raise_signal, signal
from types import CodeType, FrameType, FunctionType
from typing import TYPE_CHECKING

import outcome

import trio
from trio._util import final

if TYPE_CHECKING:
    from collections.abc import Callable

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
        reader: r.Reader | None = None,
    ) -> None:
        super().__init__(locals=repl_locals)
        self.compile.compiler.flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT
        self.reader = reader
        self.trim_first_char = False
        self.interrupted = False

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

    def raw_input(self, prompt: str = "") -> str:
        def install_handler() -> Callable[[int, FrameType | None], None] | int | None:
            def handler(sig: int, frame: FrameType | None) -> None:
                self.interrupted = True

            return signal(SIGINT, handler)

        prev_handler = trio.from_thread.run_sync(install_handler)

        assert self.reader is not None
        self.reader.ps1 = prompt
        self.interrupted = False
        self.reader.prepare()
        try:
            self.reader.refresh()
            while not self.reader.finished and not self.interrupted:
                if not self.reader.handle1(block=False):
                    # let's avoid busy waiting
                    if CPYTHON_VENDOR:
                        self.reader.console.wait(100)
                    else:
                        self.reader.console.pollob.poll(100)

            if self.interrupted:
                if not CPYTHON_VENDOR:
                    self.trim_first_char = True
                raise KeyboardInterrupt
            if CPYTHON_VENDOR:
                return self.reader.get_unicode()  # type: ignore[no-any-return]
            else:
                return self.reader.get_str()  # type: ignore[no-any-return]
        finally:
            trio.from_thread.run_sync(signal, SIGINT, prev_handler)
            self.reader.restore()

    if not CPYTHON_VENDOR:
        # pyrepl has some special handling to make sure that
        # the console is always ended in `\r\n` when done.
        # However, InteractiveConsole assumes that the input
        # was exited without a newline! So we need this hack.
        def write(self, output: str) -> None:
            if self.trim_first_char:
                assert output == "\nKeyboardInterrupt\n"
                sys.stderr.write(output[1:])
                self.trim_first_char = False
            else:
                sys.stderr.write(output)


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
    # Otherwise, we would not be able to run `multiline_input` in a
    # child thread.
    reader = readline._get_reader()

    if not CPYTHON_VENDOR:
        # The default `interrupt` command finishes the console, which
        # adds an extra newline. Unforgivable!
        class interrupt(commands.FinishCommand):  # type: ignore[misc,no-any-unimported]
            def do(self) -> None:
                raise_signal(SIGINT)

        reader.commands["interrupt"] = interrupt

    console = TrioInteractiveConsole(repl_locals, reader)
    trio.run(run_repl, console)
