from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import sys
import sysconfig
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import pytest

import trio

from .. import _core
from .._core._tests.tutil import slow
from .._signals import _signal_handler, get_pending_signal_count, open_signal_receiver

if TYPE_CHECKING:
    from types import FrameType


@pytest.mark.parametrize("native_signum", [signal.SIGINT, signal.SIGILL])
def test_signal_handler_rejects_native_before_changing_handlers(
    monkeypatch: pytest.MonkeyPatch,
    native_signum: signal.Signals,
) -> None:
    original_getsignal = signal.getsignal

    def getsignal(signum: int) -> object:
        if signum == native_signum:
            return None
        return original_getsignal(signum)

    def unexpected_signal(*args: object) -> NoReturn:
        raise AssertionError("Changed a handler before checking all signals")

    monkeypatch.setattr(signal, "getsignal", getsignal)
    monkeypatch.setattr(signal, "signal", unexpected_signal)
    with pytest.raises(
        RuntimeError, match="C-level handler cannot be restored by Python"
    ):
        with _signal_handler([signal.SIGINT, signal.SIGILL], signal.SIG_IGN):
            pytest.fail("Accepted a native handler")  # pragma: no cover


@slow
@pytest.mark.skipif(
    os.name != "posix" or sys.implementation.name != "cpython",
    reason="Requires a POSIX CPython embedding host",
)
def test_open_signal_receiver_preserves_native_sigint_handler(tmp_path: Path) -> None:
    # Python only reports None if the C handler predates interpreter startup.
    # Changing libc's handler after startup leaves Python's cached handler intact.
    compiler = shlex.split(sysconfig.get_config_var("CC") or "cc")
    config = (
        Path(sys.base_prefix) / "bin" / f"python{sysconfig.get_python_version()}-config"
    )
    if shutil.which(compiler[0]) is None or not config.is_file():
        pytest.skip("Requires a C compiler and python-config with embedding support")

    source = tmp_path / "native_signal_host.c"
    source.write_text(
        textwrap.dedent("""\
            #include <Python.h>
            #include <signal.h>
            #include <stdio.h>

            static volatile sig_atomic_t native_count = 0;

            static void native_sigint(int signum) {
                (void)signum;
                native_count++;
            }

            int main(int argc, char **argv) {
                if (signal(SIGINT, native_sigint) == SIG_ERR) return 2;
                int result = Py_BytesMain(argc, argv);
                if (result != 0) return result;
                if (native_count != 4) {
                    fprintf(stderr, "Native SIGINT deliveries: %d, expected 4\\n",
                            (int)native_count);
                    return 3;
                }
                return 0;
            }
            """),
        encoding="utf-8",
    )
    flags = shlex.split(
        subprocess.check_output(
            [str(config), "--includes", "--embed", "--ldflags"],
            text=True,
            timeout=60,
        ),
    )
    executable = tmp_path / "native_signal_host"
    # Relocatable Python builds may omit their library directory from --ldflags.
    libdir = sysconfig.get_config_var("LIBDIR") or str(Path(sys.base_prefix) / "lib")
    compiled = subprocess.run(
        [
            *compiler,
            str(source),
            "-o",
            str(executable),
            "-L",
            libdir,
            f"-Wl,-rpath,{libdir}",
            *flags,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr

    script = textwrap.dedent("""\
        import signal
        import threading

        import trio
        from trio._core._ki import KIManager
        from trio._util import is_main_thread

        assert signal.getsignal(signal.SIGINT) is None
        assert is_main_thread()
        results = []
        worker = threading.Thread(target=lambda: results.append(is_main_thread()))
        worker.start()
        worker.join()
        assert results == [False]

        manager = KIManager()
        manager.install(lambda: None, True)
        assert manager.handler is None
        manager.close()

        async def main():
            for signals in [
                (signal.SIGINT,),
                (signal.SIGINT, signal.SIGINT),
                (signal.SIGHUP, signal.SIGINT),
            ]:
                original = signal.getsignal(signal.SIGHUP)
                try:
                    with trio.open_signal_receiver(*signals):
                        raise AssertionError("Replaced a native handler")
                except RuntimeError as exc:
                    assert "C-level handler" in str(exc), str(exc)
                assert signal.getsignal(signal.SIGINT) is None
                assert signal.getsignal(signal.SIGHUP) is original
                signal.raise_signal(signal.SIGINT)

            # An unrelated receiver remains usable with the native SIGINT handler.
            original = signal.getsignal(signal.SIGHUP)
            with trio.open_signal_receiver(signal.SIGHUP) as receiver:
                signal.raise_signal(signal.SIGHUP)
                assert await receiver.__anext__() == signal.SIGHUP
            assert signal.getsignal(signal.SIGHUP) is original

        trio.run(main)
        assert signal.getsignal(signal.SIGINT) is None
        signal.raise_signal(signal.SIGINT)
        """)
    result = subprocess.run(
        [str(executable), "-c", script],
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def test_open_signal_receiver() -> None:
    orig = signal.getsignal(signal.SIGILL)
    with open_signal_receiver(signal.SIGILL) as receiver:
        # Raise it a few times, to exercise signal coalescing, both at the
        # call_soon level and at the SignalQueue level
        signal.raise_signal(signal.SIGILL)
        signal.raise_signal(signal.SIGILL)
        await _core.wait_all_tasks_blocked()
        signal.raise_signal(signal.SIGILL)
        await _core.wait_all_tasks_blocked()
        async for signum in receiver:  # pragma: no branch
            assert signum == signal.SIGILL
            break
        assert get_pending_signal_count(receiver) == 0
        signal.raise_signal(signal.SIGILL)
        async for signum in receiver:  # pragma: no branch
            assert signum == signal.SIGILL
            break
        assert get_pending_signal_count(receiver) == 0
    with pytest.raises(RuntimeError):
        await receiver.__anext__()
    assert signal.getsignal(signal.SIGILL) is orig


async def test_open_signal_receiver_restore_handler_after_one_bad_signal() -> None:
    orig = signal.getsignal(signal.SIGILL)
    with pytest.raises(
        ValueError,
        match=r"(signal number out of range|invalid signal value)$",
    ):
        with open_signal_receiver(signal.SIGILL, 1234567):
            pass  # pragma: no cover
    # Still restored even if we errored out
    assert signal.getsignal(signal.SIGILL) is orig


def test_open_signal_receiver_empty_fail() -> None:
    with pytest.raises(TypeError, match="No signals were provided"):
        with open_signal_receiver():
            pass


async def test_open_signal_receiver_restore_handler_after_duplicate_signal() -> None:
    orig = signal.getsignal(signal.SIGILL)
    with open_signal_receiver(signal.SIGILL, signal.SIGILL):
        pass
    # Still restored correctly
    assert signal.getsignal(signal.SIGILL) is orig


async def test_catch_signals_wrong_thread() -> None:
    async def naughty() -> None:
        with open_signal_receiver(signal.SIGINT):
            pass  # pragma: no cover

    with pytest.raises(RuntimeError):
        await trio.to_thread.run_sync(trio.run, naughty)


async def test_open_signal_receiver_conflict() -> None:
    with pytest.RaisesGroup(trio.BusyResourceError):
        with open_signal_receiver(signal.SIGILL) as receiver:
            async with trio.open_nursery() as nursery:
                nursery.start_soon(receiver.__anext__)
                nursery.start_soon(receiver.__anext__)


# Blocks until all previous calls to run_sync_soon(idempotent=True) have been
# processed.
async def wait_run_sync_soon_idempotent_queue_barrier() -> None:
    ev = trio.Event()
    token = _core.current_trio_token()
    token.run_sync_soon(ev.set, idempotent=True)
    await ev.wait()


async def test_open_signal_receiver_no_starvation() -> None:
    # Set up a situation where there are always 2 pending signals available to
    # report, and make sure that instead of getting the same signal reported
    # over and over, it alternates between reporting both of them.
    with open_signal_receiver(signal.SIGILL, signal.SIGFPE) as receiver:
        try:
            print(signal.getsignal(signal.SIGILL))
            previous = None
            for _ in range(10):
                signal.raise_signal(signal.SIGILL)
                signal.raise_signal(signal.SIGFPE)
                await wait_run_sync_soon_idempotent_queue_barrier()
                if previous is None:
                    previous = await receiver.__anext__()
                else:
                    got = await receiver.__anext__()
                    assert got in [signal.SIGILL, signal.SIGFPE]
                    assert got != previous
                    previous = got
            # Clear out the last signal so that it doesn't get redelivered
            while get_pending_signal_count(receiver) != 0:
                await receiver.__anext__()
        except BaseException:  # pragma: no cover
            # If there's an unhandled exception above, then exiting the
            # open_signal_receiver block might cause the signal to be
            # redelivered and give us a core dump instead of a traceback...
            import traceback

            traceback.print_exc()


async def test_catch_signals_race_condition_on_exit() -> None:
    delivered_directly: set[int] = set()

    def direct_handler(signo: int, frame: FrameType | None) -> None:
        delivered_directly.add(signo)

    print(1)
    # Test the version where the call_soon *doesn't* have a chance to run
    # before we exit the with block:
    with _signal_handler({signal.SIGILL, signal.SIGFPE}, direct_handler):
        with open_signal_receiver(signal.SIGILL, signal.SIGFPE) as receiver:
            signal.raise_signal(signal.SIGILL)
            signal.raise_signal(signal.SIGFPE)
        await wait_run_sync_soon_idempotent_queue_barrier()
    assert delivered_directly == {signal.SIGILL, signal.SIGFPE}
    delivered_directly.clear()

    print(2)
    # Test the version where the call_soon *does* have a chance to run before
    # we exit the with block:
    with _signal_handler({signal.SIGILL, signal.SIGFPE}, direct_handler):
        with open_signal_receiver(signal.SIGILL, signal.SIGFPE) as receiver:
            signal.raise_signal(signal.SIGILL)
            signal.raise_signal(signal.SIGFPE)
            await wait_run_sync_soon_idempotent_queue_barrier()
            assert get_pending_signal_count(receiver) == 2
    assert delivered_directly == {signal.SIGILL, signal.SIGFPE}
    delivered_directly.clear()

    # Again, but with a SIG_IGN signal:

    print(3)
    with _signal_handler({signal.SIGILL}, signal.SIG_IGN):
        with open_signal_receiver(signal.SIGILL) as receiver:
            signal.raise_signal(signal.SIGILL)
        await wait_run_sync_soon_idempotent_queue_barrier()
    # test passes if the process reaches this point without dying

    print(4)
    with _signal_handler({signal.SIGILL}, signal.SIG_IGN):
        with open_signal_receiver(signal.SIGILL) as receiver:
            signal.raise_signal(signal.SIGILL)
            await wait_run_sync_soon_idempotent_queue_barrier()
            assert get_pending_signal_count(receiver) == 1
    # test passes if the process reaches this point without dying

    # Check exception chaining if there are multiple exception-raising
    # handlers
    def raise_handler(signum: int, frame: FrameType | None) -> NoReturn:
        raise RuntimeError(signum)

    with _signal_handler({signal.SIGILL, signal.SIGFPE}, raise_handler):
        with pytest.raises(RuntimeError) as excinfo:
            with open_signal_receiver(signal.SIGILL, signal.SIGFPE) as receiver:
                signal.raise_signal(signal.SIGILL)
                signal.raise_signal(signal.SIGFPE)
                await wait_run_sync_soon_idempotent_queue_barrier()
                assert get_pending_signal_count(receiver) == 2
        exc = excinfo.value
        signums = {exc.args[0]}
        assert isinstance(exc.__context__, RuntimeError)
        signums.add(exc.__context__.args[0])
        assert signums == {signal.SIGILL, signal.SIGFPE}
