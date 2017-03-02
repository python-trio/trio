import pytest
import sys
import os
import signal
import threading
import contextlib

from async_generator import async_generator, yield_

from ... import _core
from ...testing import wait_all_tasks_blocked
from ..._util import acontextmanager

if os.name == "nt":
    # I looked at this pretty hard and I'm pretty sure there isn't any way to
    # deliver a real CTRL_C_EVENT to the test process that works reliably on
    # Appveyor etc.
    #
    # You can make a synthetic CTRL_C_EVENT using GenerateConsoleCtrlEvent:
    #
    #    https://msdn.microsoft.com/en-us/library/windows/desktop/ms683155(v=vs.85).aspx
    #
    # However, this isn't directed at a *process*. Your options are:
    #
    # 1) send it to process 0, which means "everyone attached to this
    # console".
    #
    # 2) If a process is a group leader, then you can pass in its PID, and
    # which case it might send it to just the processes that are in that group
    # and also share a console with the caller. Or maybe not -- the page above
    # claims that this doesn't work for CTRL_C_EVENT, only
    # CTRL_BREAK_EVENT. But it's clearly wrong, because it did work for me in
    # some cases?
    #
    # 3) If a process is *not* a group leader and you pass in its PID, then
    # the results are not documented. But empirically it seems like it might
    # act like you passed 0:
    #
    #    https://stackoverflow.com/questions/42180468
    #
    # So our problem is that we want to deliver a CTRL_C_EVENT to the current
    # process, without causing side-effects like freezing Appveyor.
    #
    # There are two strategies that suggest themselves: either run pytest as a
    # new process group, so we're a process group leader, or else run pytest
    # on a new console.
    #
    # There are some annoyances here that I do know how to overcome. If
    # creating a new process group: (a) we need to spawn Python directly,
    # e.g. "python -m pytest". If we use a entry-point script like "pytest",
    # or a launcher like "py", then it doesn't work -- probably because then
    # the launching process ends up as group leader, so the actual test
    # process isn't, and that breaks things as per above. (b)
    # CREATE_NEW_PROCESS_GROUP also sets an internal flag that makes it so the
    # spawned process ignores CTRL_C_EVENT. We have to flip that flag back by
    # hand, using SetConsoleCtrlHandler(NULL, FALSE).
    #
    # If creating a new console: we need to hide the new console window
    # (shell=True in subprocess.Popen), and pass in a stdout/stderr PIPE and
    # pump the output back by hand. (Otherwise the output goes to the new
    # console window, which on Appveyor is obviously useless regardless of
    # whether the new window is hidden.) AFAICT there's no way to directly
    # pass in the original console's output handles as handles for the child
    # process, probably because console handles are weird virtual handle
    # things.
    #
    # The docs claim that if you try to do both at once (CREATE_NEW_CONSOLE |
    # CREATE_NEW_PROCESS_GROUP) then that's equivalent to CREATE_NEW_CONSOLE
    # alone. I haven't tried to check this.
    #
    # There is also some subtlety required when using GenerateConsoleCtrlEvent
    # to make sure that the event is actually delivered at the right time --
    # for the tests we want the Python-level signal handler to run before we
    # exit ki_self, but this is tricky because the CTRL_C_EVENT handler runs
    # in a new thread that isn't synchronized to anything.
    #
    # Anyway. Having done all the work to deal with this issues, both of these
    # approaches work... kind of. They work locally. And I was able to get
    # them to work seemingly-reliably on Appveyor (like, passing 8/8 runs),
    # BUT this required weird tweaking -- in particular, the working runs were
    # like
    #
    #    python -u -m pytest -v -s
    #
    # Yes, it is critically important that we run python with unbuffered stdio
    # (-u). Without this then there are freezes on a regular (but not 100%
    # deterministic) basis. Maybe there is something where you have to
    # actually interact with the console in order to get CTRL_C_EVENT
    # delivered? It's totally baffling to me.
    #
    # So anyway, I just don't trust this. I'd much rather have a test suite
    # that runs 100% reliably and tests 99% of the stuff than a test suite
    # that runs 99% reliably and tests 100% of the stuff. So we fake it.
    def ki_self():
        assert threading.current_thread() == threading.main_thread()
        handler = signal.getsignal(signal.SIGINT)
        handler(signal.SIGINT, sys._getframe())
else:
    # On Unix, kill invokes the C handler synchronously, in this process only,
    # and then os.kill immediately checks for this and runs the Python handler
    # before returning. So... that's easy.
    def ki_self():
        os.kill(os.getpid(), signal.SIGINT)

def test_ki_self():
    with pytest.raises(KeyboardInterrupt):
        ki_self()

async def test_ki_enabled():
    # Regular tasks aren't KI-protected
    assert not _core.currently_ki_protected()

    # Low-level call-soon callbacks are KI-protected
    call_soon = _core.current_call_soon_thread_and_signal_safe()
    record = []
    def check():
        record.append(_core.currently_ki_protected())
    call_soon(check)
    await wait_all_tasks_blocked()
    assert record == [True]

    @_core.enable_ki_protection
    def protected():
        assert _core.currently_ki_protected()
        unprotected()

    @_core.disable_ki_protection
    def unprotected():
        assert not _core.currently_ki_protected()

    protected()

    @_core.enable_ki_protection
    async def aprotected():
        assert _core.currently_ki_protected()
        await aunprotected()

    @_core.disable_ki_protection
    async def aunprotected():
        assert not _core.currently_ki_protected()

    await aprotected()

    # make sure that the decorator here overrides the automatic manipulation
    # that spawn() does:
    async with _core.open_nursery() as nursery:
        nursery.spawn(aprotected)
        nursery.spawn(aunprotected)

    @_core.enable_ki_protection
    def gen_protected():
        assert _core.currently_ki_protected()
        yield

    for _ in gen_protected():
        pass

    @_core.disable_ki_protection
    def gen_unprotected():
        assert not _core.currently_ki_protected()
        yield

    for _ in gen_unprotected():
        pass


# This used to be broken due to
#
#   https://bugs.python.org/issue29590
#
# Specifically, after a coroutine is resumed with .throw(), then the stack
# makes it look like the immediate caller is the function that called
# .throw(), not the actual caller. So child() here would have a caller deep in
# the guts of the run loop, and always be protected, even when it shouldn't
# have been. (Solution: we don't use .throw() anymore.)
async def test_ki_enabled_after_yield_briefly():
    @_core.enable_ki_protection
    async def protected():
        await child(True)

    @_core.disable_ki_protection
    async def unprotected():
        await child(False)

    async def child(expected):
        import traceback
        traceback.print_stack()
        assert _core.currently_ki_protected() == expected
        await _core.yield_briefly()
        traceback.print_stack()
        assert _core.currently_ki_protected() == expected

    await protected()
    await unprotected()


# This also used to be broken due to
#   https://bugs.python.org/issue29590
async def test_generator_based_context_manager_throw():
    @contextlib.contextmanager
    @_core.enable_ki_protection
    def protected_manager():
        assert _core.currently_ki_protected()
        try:
            yield
        finally:
            assert _core.currently_ki_protected()

    with protected_manager():
        assert not _core.currently_ki_protected()

    with pytest.raises(KeyError):
        # This is the one that used to fail
        with protected_manager():
            raise KeyError


async def test_agen_protection():
    @_core.enable_ki_protection
    @async_generator
    async def agen_protected1():
        assert _core.currently_ki_protected()
        try:
            await yield_()
        finally:
            assert _core.currently_ki_protected()

    @_core.disable_ki_protection
    @async_generator
    async def agen_unprotected1():
        assert not _core.currently_ki_protected()
        try:
            await yield_()
        finally:
            assert not _core.currently_ki_protected()

    # Swap the order of the decorators:
    @async_generator
    @_core.enable_ki_protection
    async def agen_protected2():
        assert _core.currently_ki_protected()
        try:
            await yield_()
        finally:
            assert _core.currently_ki_protected()

    @async_generator
    @_core.disable_ki_protection
    async def agen_unprotected2():
        assert not _core.currently_ki_protected()
        try:
            await yield_()
        finally:
            assert not _core.currently_ki_protected()

    for agen_fn in [
            agen_protected1, agen_protected2,
            agen_unprotected1, agen_unprotected2,
    ]:
        async for _ in agen_fn():
            assert not _core.currently_ki_protected()

        async with acontextmanager(agen_fn)():
            assert not _core.currently_ki_protected()

        # Another case that's tricky due to:
        #   https://bugs.python.org/issue29590
        with pytest.raises(KeyError):
            async with acontextmanager(agen_fn)():
                raise KeyError


# Test the case where there's no magic local anywhere in the call stack
def test_ki_enabled_out_of_context():
    assert not _core.currently_ki_protected()


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
            print("killing, protection =", _core.currently_ki_protected())
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
    async def check_kill_during_shutdown():
        call_soon = _core.current_call_soon_thread_and_signal_safe()
        def kill_during_shutdown():
            assert _core.currently_ki_protected()
            try:
                call_soon(kill_during_shutdown)
            except _core.RunFinishedError:
                # it's too late for regular handling! handle this!
                print("kill! kill!")
                ki_self()
        call_soon(kill_during_shutdown)

    with pytest.raises(KeyboardInterrupt):
        _core.run(check_kill_during_shutdown)

    # KI arrives very early, before main is even spawned
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
        assert _core.currently_ki_protected()
        ki_self()
        with pytest.raises(KeyboardInterrupt):
            await _core.yield_if_cancelled()
    _core.run(main)

    # KI arrives while main task is not abortable, b/c already scheduled
    print("check 6")
    @_core.enable_ki_protection
    async def main():
        assert _core.currently_ki_protected()
        ki_self()
        await _core.yield_briefly_no_cancel()
        await _core.yield_briefly_no_cancel()
        await _core.yield_briefly_no_cancel()
        with pytest.raises(KeyboardInterrupt):
            await _core.yield_briefly()
    _core.run(main)

    # KI arrives while main task is not abortable, b/c refuses to be aborted
    print("check 7")
    @_core.enable_ki_protection
    async def main():
        assert _core.currently_ki_protected()
        ki_self()
        task = _core.current_task()
        def abort(_):
            _core.reschedule(task, _core.Value(1))
            return _core.Abort.FAILED
        assert await _core.yield_indefinitely(abort) == 1
        with pytest.raises(KeyboardInterrupt):
            await _core.yield_briefly()
    _core.run(main)

    # KI delivered via slow abort
    print("check 8")
    @_core.enable_ki_protection
    async def main():
        assert _core.currently_ki_protected()
        ki_self()
        task = _core.current_task()
        def abort(raise_cancel):
            result = _core.Result.capture(raise_cancel)
            _core.reschedule(task, result)
            return _core.Abort.FAILED
        with pytest.raises(KeyboardInterrupt):
            assert await _core.yield_indefinitely(abort)
        await _core.yield_briefly()
    _core.run(main)

    # KI arrives just before main task exits, so the call_soon machinery is
    # still functioning and will accept the callback to deliver the KI, but by
    # the time the callback is actually run, main has exited and can't be
    # aborted.
    print("check 9")
    @_core.enable_ki_protection
    async def main():
        ki_self()
    with pytest.raises(KeyboardInterrupt):
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
