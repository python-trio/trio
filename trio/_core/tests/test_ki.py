import pytest
import sys
import os
import signal
import threading

from ... import _core
from ...testing import wait_run_loop_idle

async def test_ki_enabled():
    # Regular tasks aren't KI-protected
    assert not _core.ki_protected()

    # Low-level call-soon callbacks are KI-protected
    call_soon = _core.current_call_soon_thread_and_signal_safe()
    record = []
    def check_sync():
        record.append(_core.ki_protected())
    async def check_async():
        record.append(_core.ki_protected())
    call_soon(check_sync)
    call_soon(check_async, spawn=True)
    await wait_run_loop_idle()
    assert record == [True, True]

    @_core.enable_ki_protection
    def protected():
        assert _core.ki_protected()
        unprotected()

    @_core.disable_ki_protection
    def unprotected():
        assert not _core.ki_protected()

    protected()

    @_core.enable_ki_protection
    async def aprotected():
        assert _core.ki_protected()
        await aunprotected()

    @_core.disable_ki_protection
    async def aunprotected():
        assert not _core.ki_protected()

    await aprotected()


# Test the case where there's no magic local anywhere in the call stack
def test_ki_enabled_out_of_context():
    assert not _core.ki_protected()


@pytest.mark.skipif(os.name == "nt", reason="need unix signals")
def test_ki_protection_works():
    async def sleeper(name, record):
        try:
            while True:
                await _core.yield_briefly()
        except _core.KeyboardInterruptCancelled:
            record.add((name + " ok"))

    async def raiser(name, record):
        try:
            # os.kill runs signal handlers before returning, so we don't need
            # to worry that the handler will be delayed
            print("killing, protection =", _core.ki_protected())
            os.kill(os.getpid(), signal.SIGINT)
        except _core.KeyboardInterruptCancelled:
            print("raised!")
            # Make sure we aren't getting cancelled as well as siginted
            await _core.yield_briefly()
            record.add((name + " raise ok"))
        else:
            print("didn't raise!")
            # If we didn't raise (b/c protected), then we *should* get
            # cancelled at the next opportunity
            try:
                while True:
                    await _core.yield_briefly()
            except _core.KeyboardInterruptCancelled:
                record.add((name + " cancel ok"))

    # simulated control-C during raiser, which is *unprotected*
    record = set()
    async def check_unprotected_kill():
        await _core.spawn(sleeper, "s1", record)
        await _core.spawn(sleeper, "s2", record)
        await _core.spawn(raiser, "r1", record)
    with pytest.raises(_core.KeyboardInterruptCancelled):
        _core.run(check_unprotected_kill)
    assert record == {"s1 ok", "s2 ok", "r1 raise ok"}

    # simulated control-C during raiser, which is *protected*
    record = set()
    async def check_protected_kill():
        await _core.spawn(sleeper, "s1", record)
        await _core.spawn(sleeper, "s2", record)
        await _core.spawn(_core.enable_ki_protection(raiser), "r1", record)
    with pytest.raises(_core.KeyboardInterruptCancelled):
        _core.run(check_protected_kill)
    assert record == {"s1 ok", "s2 ok", "r1 cancel ok"}

    # kill at last moment still raises (call_soon until it raises an error,
    # then kill)
    record = set()
    async def check_kill_during_shutdown():
        call_soon = _core.current_call_soon_thread_and_signal_safe()
        def kill_during_shutdown():
            try:
                call_soon(kill_during_shutdown)
            except _core.RunFinishedError:
                # it's too late for regular handling! handle this!
                print("kill! kill!")
                os.kill(os.getpid(), signal.SIGINT)
        call_soon(kill_during_shutdown)

    with pytest.raises(KeyboardInterrupt):
        _core.run(check_kill_during_shutdown)


def test_ki_is_good_neighbor():
    # in the unlikely event someone overwrites our signal handler, we leave
    # the overwritten one be
    try:
        orig = signal.getsignal(signal.SIGINT)

        def my_handler(signum, frame):  # pragma: no cover
            pass
        async def main():
            signal.signal(signal.SIGINT, my_handler)
        _core.run(main)

        assert signal.getsignal(signal.SIGINT) is my_handler
    finally:
        signal.signal(signal.SIGINT, orig)
