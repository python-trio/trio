"""Starts an interactive interpreter session that supports top-level
`await`-ing.

To start a new session, run the command:

.. code-block:: shell

   python -m trio

Modeled after the standard library's `asyncio.__main__`. See:

    https://github.com/python/cpython/blob/master/Lib/asyncio/__main__.py
"""

import ast
import code
import concurrent.futures
import contextlib
import inspect
import sys
import threading
import types

import trio


class TrioInteractiveConsole(code.InteractiveConsole):
    def __init__(self, locals, nursery):
        super().__init__(locals)
        self.compile.compiler.flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT
        self.nursery = nursery

    def runcode(self, code):
        func = types.FunctionType(code, self.locals)
        future = concurrent.futures.Future()

        try:
            result = func()
        except SystemExit:
            raise
        except BaseException as exc:
            future.set_exception(exc)
        else:
            if not inspect.iscoroutine(result):
                future.set_result(result)
            else:
                await_in_bg = threading.Thread(
                    target=trio.run, args=(_await, result, future), daemon=True
                )
                await_in_bg.start()

        try:
            return future.result()
        except SystemExit:
            raise
        except KeyboardInterrupt:
            self.write("\nKeyboardInterrupt\n")
        except BaseException:
            self.showtraceback()


async def _await(awaitable, future):
    try:
        value = await awaitable
    except SystemExit:
        raise
    except BaseException as exc:
        future.set_exception(exc)
    else:
        future.set_result(value)


async def main(repl_locals):
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


if __name__ == "__main__":
    with contextlib.suppress(ModuleNotFoundError):
        pass

    repl_locals = {"trio": trio}
    for key in {
        "__name__",
        "__package__",
        "__loader__",
        "__spec__",
        "__builtins__",
        "__file__",
    }:
        repl_locals[key] = locals()[key]

    trio.run(main, repl_locals)
