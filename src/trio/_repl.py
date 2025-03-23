from __future__ import annotations

import ast
import contextlib
import inspect
import sys
import types
import warnings
from code import InteractiveConsole

import outcome

import trio
import trio.lowlevel
from trio._util import final


class SuppressDecorator(contextlib.ContextDecorator, contextlib.suppress):
    pass


@final
class TrioInteractiveConsole(InteractiveConsole):
    # code.InteractiveInterpreter defines locals as Mapping[str, Any]
    # but when we pass this to FunctionType it expects a dict. So
    # we make the type more specific on our subclass
    locals: dict[str, object]

    def __init__(self, repl_locals: dict[str, object] | None = None) -> None:
        super().__init__(locals=repl_locals)
        self.token: trio.lowlevel.TrioToken | None = None
        self.compile.compiler.flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT

    def runcode(self, code: types.CodeType) -> None:
        func = types.FunctionType(code, self.locals)
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

    if sys.platform == "win32":

        def raw_input(self, prompt: str = "") -> str:
            try:
                return input(prompt)
            except EOFError:
                # check if trio has a pending KI
                trio.from_thread.run(trio.lowlevel.checkpoint_if_cancelled)
                raise

    else:

        def raw_input(self, prompt: str = "") -> str:
            from signal import SIGINT, signal

            interrupted = False

            if self.token is None:
                self.token = trio.from_thread.run_sync(trio.lowlevel.current_trio_token)

            @SuppressDecorator(KeyboardInterrupt)
            @trio.lowlevel.disable_ki_protection
            def newline():
                import fcntl
                import termios

                # Fake up a newline char as if user had typed it at
                fcntl.ioctl(sys.stdin, termios.TIOCSTI, b"\n")

            def handler(sig: int, frame: types.FrameType | None) -> None:
                nonlocal interrupted
                interrupted = True
                self.token.run_sync_soon(newline, idempotent=True)

            prev_handler = trio.from_thread.run_sync(signal, SIGINT, handler)
            try:
                return input(prompt)
            finally:
                trio.from_thread.run_sync(signal, SIGINT, prev_handler)
                if interrupted:
                    raise KeyboardInterrupt


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
