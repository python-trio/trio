import os
import signal
import threading
import queue as stdlib_queue

import pytest

from .. import _core
from .._signals import catch_signals, _signal_handler, _signal_raise
from .._sync import Event

async def test_catch_signals():
    print = lambda *args: None
    orig = signal.getsignal(signal.SIGILL)
    print(orig)
    with catch_signals([signal.SIGILL]) as queue:
        # Raise it a few times, to exercise signal coalescing, both at the
        # call_soon level and at the SignalQueue level
        _signal_raise(signal.SIGILL)
        _signal_raise(signal.SIGILL)
        await _core.wait_all_tasks_blocked()
        _signal_raise(signal.SIGILL)
        await _core.wait_all_tasks_blocked()
        async for batch in queue:  # pragma: no branch
            assert batch == {signal.SIGILL}
            break
        _signal_raise(signal.SIGILL)
        async for batch in queue:  # pragma: no branch
            assert batch == {signal.SIGILL}
            break
    with pytest.raises(RuntimeError):
        await queue.__anext__()
    assert signal.getsignal(signal.SIGILL) is orig


def test_catch_signals_wrong_thread():
    threadqueue = stdlib_queue.Queue()
    async def naughty():
        try:
            with catch_signals([signal.SIGINT]) as _:
                pass  # pragma: no cover
        except Exception as exc:
            threadqueue.put(exc)
        else:  # pragma: no cover
            threadqueue.put(None)
    thread = threading.Thread(target=_core.run, args=(naughty,))
    thread.start()
    thread.join()
    exc = threadqueue.get_nowait()
    assert type(exc) is RuntimeError


async def test_catch_signals_race_condition_on_exit():
    delivered_directly = set()

    def direct_handler(signo, frame):
        delivered_directly.add(signo)

    async def wait_call_soon_idempotent_queue_barrier():
        ev = Event()
        call_soon = _core.current_call_soon_thread_and_signal_safe()
        call_soon(ev.set, idempotent = True)
        await ev.wait()

    print(1)
    # Test the version where the call_soon *doesn't* have a chance to run
    # before we exit the with block:
    with _signal_handler({signal.SIGILL, signal.SIGFPE}, direct_handler):
        with catch_signals({signal.SIGILL, signal.SIGFPE}) as queue:
            _signal_raise(signal.SIGILL)
            _signal_raise(signal.SIGFPE)
        await wait_call_soon_idempotent_queue_barrier()
    assert delivered_directly == {signal.SIGILL, signal.SIGFPE}
    delivered_directly.clear()

    print(2)
    # Test the version where the call_soon *does* have a chance to run before
    # we exit the with block:
    with _signal_handler({signal.SIGILL, signal.SIGFPE}, direct_handler):
        with catch_signals({signal.SIGILL, signal.SIGFPE}) as queue:
            _signal_raise(signal.SIGILL)
            _signal_raise(signal.SIGFPE)
            await wait_call_soon_idempotent_queue_barrier()
            assert len(queue._pending) == 2
    assert delivered_directly == {signal.SIGILL, signal.SIGFPE}
    delivered_directly.clear()

    # Again, but with a SIG_IGN signal:

    print(3)
    with _signal_handler({signal.SIGILL}, signal.SIG_IGN):
        with catch_signals({signal.SIGILL}) as queue:
            _signal_raise(signal.SIGILL)
        await wait_call_soon_idempotent_queue_barrier()
    # test passes if the process reaches this point without dying

    print(4)
    with _signal_handler({signal.SIGILL}, signal.SIG_IGN):
        with catch_signals({signal.SIGILL}) as queue:
            _signal_raise(signal.SIGILL)
            await wait_call_soon_idempotent_queue_barrier()
            assert len(queue._pending) == 1
    # test passes if the process reaches this point without dying

    # Check exception chaining if there are multiple exception-raising
    # handlers
    def raise_handler(signum, _):
        raise RuntimeError(signum)

    with _signal_handler({signal.SIGILL, signal.SIGFPE}, direct_handler):
        try:
            with catch_signals({signal.SIGILL, signal.SIGFPE}) as queue:
                _signal_raise(signal.SIGILL)
                _signal_raise(signal.SIGFPE)
                await wait_call_soon_idempotent_queue_barrier()
                assert len(queue._pending) == 2
        except RuntimeError as exc:
            signums = {exc.args[0]}
            assert isinstance(exc.__context__, RuntimeError)
            signums.add(exc.__context__.args[0])
            assert signums == {signal.SIGILL, signal.SIGFPE}
