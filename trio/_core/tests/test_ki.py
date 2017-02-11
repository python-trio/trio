import pytest
import sys
import os
import signal
import threading
import time

from ... import _core
from ...testing import wait_run_loop_idle

if os.name == "nt":
    from .._windows_cffi import ffi, kernel32
    # Make sure that we're not ignoring CTRL_C_EVENT. (This is important b/c
    # on appveyor we run the testsuite with CREATE_NEW_PROCESS_GROUP, which
    # sets the CTRL_C_EVENT ignore flag to TRUE in children as a side-effect.)
    kernel32.SetConsoleCtrlHandler(ffi.NULL, 0)

    def ki_self():
        # On Windows, GenerateConsoleCtrlEvent spawns a thread to run the C
        # handler. We want the event to happen right *here*, so we manually
        # rendezvous with the handler before continuing. (Windows allows
        # multiple handlers for the same event, so this isn't too hard.)
        ev = threading.Event()
        @ffi.callback("BOOL WINAPI(DWORD)")
        def cb(dwCtrlType):
            print("ConsoleCtrlHandler callback!", dwCtrlType)
            ev.set()
            # 0 = FALSE = keep running handlers after this
            return 0
        try:
            kernel32.SetConsoleCtrlHandler(cb, 1)
            # os.kill has a special case where if you pass it CTRL_C_EVENT on
            # Windows then it calls GenerateConsoleCtrlEvent. Passing SIGINT
            # is totally different -- that just calls TerminateProcess. So
            # this raises a CTRL_C_EVENT in the current process
            # group. Hopefully that's just us...
            os.kill(0, signal.CTRL_C_EVENT)
            ev.wait()
        finally:
            kernel32.SetConsoleCtrlHandler(cb, 0)
        # Even this isn't quite enough because it only guarantees that the
        # first handler has run; it doesn't guarantee that the later ones
        # (like CPython's!) have, or that CPython has noticed and run the
        # Python-level handler. So we also do a short sleep.
        #
        # It this turns out to be unreliable, another approach would be to
        # rendezvous by registering our own Python-level signal handler that
        # calls the previously registered one and then signals the event. I'm
        # a little hesitant to mess with the Python-level signal handler here
        # since it's what we're trying to test, but it'd probably be okay...
        time.sleep(0.1)
else:
    # On Unix, kill invokes the C handler synchronously, and then os.kill
    # immediately checks for this and runs the Python handler before
    # returning. So... that's easy.
    def ki_self():
        os.kill(os.getpid(), signal.SIGINT)

def test_ki_self():
    try:
        ki_self()
    except KeyboardInterrupt:
        pass
    else:
        assert False

async def test_ki_enabled():
    # Regular tasks aren't KI-protected
    assert not _core.ki_protected()

    # Low-level call-soon callbacks are KI-protected
    call_soon = _core.current_call_soon_thread_and_signal_safe()
    record = []
    def check():
        record.append(_core.ki_protected())
    call_soon(check)
    await wait_run_loop_idle()
    assert record == [True]

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


def test_ki_protection_works():
    async def sleeper(name, record):
        try:
            while True:
                await _core.yield_briefly()
        except _core.Cancelled:
            record.add((name + " ok"))

    async def raiser(name, record):
        try:
            # os.kill runs signal handlers before returning, so we don't need
            # to worry that the handler will be delayed
            print("killing, protection =", _core.ki_protected())
            ki_self()
        except KeyboardInterrupt:
            print("raised!")
            # Make sure we aren't getting cancelled as well as siginted
            await _core.yield_briefly()
            record.add((name + " raise ok"))
            raise
        else:
            print("didn't raise!")
            # If we didn't raise (b/c protected), then we *should* get
            # cancelled at the next opportunity
            try:
                await _core.yield_indefinitely(lambda _: _core.Abort.SUCCEEDED)
            except _core.Cancelled:
                record.add((name + " cancel ok"))

    # simulated control-C during raiser, which is *unprotected*
    print("check 1")
    record = set()
    async def check_unprotected_kill():
        async with _core.open_nursery() as nursery:
            nursery.spawn(sleeper, "s1", record)
            nursery.spawn(sleeper, "s2", record)
            nursery.spawn(raiser, "r1", record)
    with pytest.raises(KeyboardInterrupt):
        _core.run(check_unprotected_kill)
    assert record == {"s1 ok", "s2 ok", "r1 raise ok"}

    # simulated control-C during raiser, which is *protected*, so the KI gets
    # delivered to the main task instead
    print("check 2")
    record = set()
    async def check_protected_kill():
        async with _core.open_nursery() as nursery:
            nursery.spawn(sleeper, "s1", record)
            nursery.spawn(sleeper, "s2", record)
            nursery.spawn(_core.enable_ki_protection(raiser), "r1", record)
            # __aexit__ blocks, and then receives the KI
    with pytest.raises(KeyboardInterrupt):
        _core.run(check_protected_kill)
    assert record == {"s1 ok", "s2 ok", "r1 cancel ok"}

    # kill at last moment still raises (call_soon until it raises an error,
    # then kill)
    print("check 3")
    record = set()
    async def check_kill_during_shutdown():
        call_soon = _core.current_call_soon_thread_and_signal_safe()
        def kill_during_shutdown():
            try:
                call_soon(kill_during_shutdown)
            except _core.RunFinishedError:
                # it's too late for regular handling! handle this!
                print("kill! kill!")
                ki_self()
        call_soon(kill_during_shutdown)

    with pytest.raises(KeyboardInterrupt):
        _core.run(check_kill_during_shutdown)

    # control-C arrives very early, before main is even spawned
    print("check 4")
    class InstrumentOfDeath:
        def before_run(self):
            ki_self()
    async def main():
        await _core.yield_briefly()
    with pytest.raises(KeyboardInterrupt):
        _core.run(main, instruments=[InstrumentOfDeath()])

    # yield_if_cancelled notices pending KI
    print("check 5")

    @_core.enable_ki_protection
    async def main():
        assert _core.ki_protected()
        ki_self()
        with pytest.raises(KeyboardInterrupt):
            await _core.yield_if_cancelled()
    _core.run(main)

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
