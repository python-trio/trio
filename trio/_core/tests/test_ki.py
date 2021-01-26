import outcome
import pytest
import sys
import os
import signal
import threading
import contextlib
import time
from typing import Any, AsyncIterator, Iterator

from async_generator import (
    async_generator,
    yield_,
    isasyncgenfunction,
    asynccontextmanager,
)

from ... import _core
from ...testing import wait_all_tasks_blocked
from ..._util import signal_raise, is_main_thread
from ..._timeouts import sleep
from .tutil import slow


def ki_self():
    signal_raise(signal.SIGINT)


def test_ki_self():
    with pytest.raises(KeyboardInterrupt):
        ki_self()


async def test_ki_enabled() -> None:
    # Regular tasks aren't KI-protected
    assert not _core.currently_ki_protected()

    # Low-level call-soon callbacks are KI-protected
    token = _core.current_trio_token()
    record: Any = []

    def check():
        record.append(_core.currently_ki_protected())

    token.run_sync_soon(check)
    await wait_all_tasks_blocked()
    assert record == [True]

    @_core.enable_ki_protection
    def protected() -> None:
        assert _core.currently_ki_protected()
        unprotected()

    @_core.disable_ki_protection
    def unprotected() -> None:
        assert not _core.currently_ki_protected()

    protected()

    @_core.enable_ki_protection
    async def aprotected() -> None:
        assert _core.currently_ki_protected()
        await aunprotected()

    @_core.disable_ki_protection
    async def aunprotected() -> None:
        assert not _core.currently_ki_protected()

    await aprotected()

    # make sure that the decorator here overrides the automatic manipulation
    # that start_soon() does:
    async with _core.open_nursery() as nursery:
        nursery.start_soon(aprotected)
        nursery.start_soon(aunprotected)

    @_core.enable_ki_protection
    def gen_protected() -> Iterator[None]:
        assert _core.currently_ki_protected()
        yield

    for _ in gen_protected():
        pass

    @_core.disable_ki_protection
    def gen_unprotected() -> Iterator[None]:
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
async def test_ki_enabled_after_yield_briefly() -> None:
    @_core.enable_ki_protection
    async def protected() -> None:
        await child(True)

    @_core.disable_ki_protection
    async def unprotected() -> None:
        await child(False)

    async def child(expected: bool) -> None:
        import traceback

        traceback.print_stack()
        assert _core.currently_ki_protected() == expected
        await _core.checkpoint()
        traceback.print_stack()
        assert _core.currently_ki_protected() == expected

    await protected()
    await unprotected()


# This also used to be broken due to
#   https://bugs.python.org/issue29590
async def test_generator_based_context_manager_throw() -> None:
    @contextlib.contextmanager
    @_core.enable_ki_protection
    def protected_manager() -> Iterator[None]:
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


async def test_agen_protection() -> None:
    @_core.enable_ki_protection
    @async_generator
    async def agen_protected1():  # type: ignore[misc]
        assert _core.currently_ki_protected()
        try:
            await yield_()
        finally:
            assert _core.currently_ki_protected()

    @_core.disable_ki_protection
    @async_generator
    async def agen_unprotected1():  # type: ignore[misc]
        assert not _core.currently_ki_protected()
        try:
            await yield_()
        finally:
            assert not _core.currently_ki_protected()

    # Swap the order of the decorators:
    @async_generator
    @_core.enable_ki_protection
    async def agen_protected2():  # type: ignore[misc]
        assert _core.currently_ki_protected()
        try:
            await yield_()
        finally:
            assert _core.currently_ki_protected()

    @async_generator
    @_core.disable_ki_protection
    async def agen_unprotected2():  # type: ignore[misc]
        assert not _core.currently_ki_protected()
        try:
            await yield_()
        finally:
            assert not _core.currently_ki_protected()

    # Native async generators
    @_core.enable_ki_protection
    async def agen_protected3() -> AsyncIterator[None]:
        assert _core.currently_ki_protected()
        try:
            yield
        finally:
            assert _core.currently_ki_protected()

    @_core.disable_ki_protection
    async def agen_unprotected3() -> AsyncIterator[None]:
        assert not _core.currently_ki_protected()
        try:
            yield
        finally:
            assert not _core.currently_ki_protected()

    for agen_fn in [
        agen_protected1,
        agen_protected2,
        agen_protected3,
        agen_unprotected1,
        agen_unprotected2,
        agen_unprotected3,
    ]:
        async for _ in agen_fn():  # noqa
            assert not _core.currently_ki_protected()

        # asynccontextmanager insists that the function passed must itself be an
        # async gen function, not a wrapper around one
        if isasyncgenfunction(agen_fn):
            async with asynccontextmanager(agen_fn)():
                assert not _core.currently_ki_protected()

            # Another case that's tricky due to:
            #   https://bugs.python.org/issue29590
            with pytest.raises(KeyError):
                async with asynccontextmanager(agen_fn)():
                    raise KeyError


# Test the case where there's no magic local anywhere in the call stack
def test_ki_disabled_out_of_context():
    assert _core.currently_ki_protected()


def test_ki_disabled_in_del() -> None:
    def nestedfunction():
        return _core.currently_ki_protected()

    def __del__():
        assert _core.currently_ki_protected()
        assert nestedfunction()

    @_core.disable_ki_protection
    def outerfunction() -> None:
        assert not _core.currently_ki_protected()
        assert not nestedfunction()
        __del__()

    __del__()
    outerfunction()
    assert nestedfunction()


def test_ki_protection_works() -> None:
    async def sleeper(name, record):
        try:
            while True:
                await _core.checkpoint()
        except _core.Cancelled:
            record.add(name + " ok")

    async def raiser(name, record):
        try:
            # os.kill runs signal handlers before returning, so we don't need
            # to worry that the handler will be delayed
            print("killing, protection =", _core.currently_ki_protected())
            ki_self()
        except KeyboardInterrupt:
            print("raised!")
            # Make sure we aren't getting cancelled as well as siginted
            await _core.checkpoint()
            record.add(name + " raise ok")
            raise
        else:
            print("didn't raise!")
            # If we didn't raise (b/c protected), then we *should* get
            # cancelled at the next opportunity
            try:
                await _core.wait_task_rescheduled(lambda _: _core.Abort.SUCCEEDED)
            except _core.Cancelled:
                record.add(name + " cancel ok")

    # simulated control-C during raiser, which is *unprotected*
    print("check 1")
    record: Any = set()

    async def check_unprotected_kill():
        async with _core.open_nursery() as nursery:
            nursery.start_soon(sleeper, "s1", record)
            nursery.start_soon(sleeper, "s2", record)
            nursery.start_soon(raiser, "r1", record)

    with pytest.raises(KeyboardInterrupt):
        _core.run(check_unprotected_kill)
    assert record == {"s1 ok", "s2 ok", "r1 raise ok"}

    # simulated control-C during raiser, which is *protected*, so the KI gets
    # delivered to the main task instead
    print("check 2")
    record = set()

    async def check_protected_kill():
        async with _core.open_nursery() as nursery:
            nursery.start_soon(sleeper, "s1", record)
            nursery.start_soon(sleeper, "s2", record)
            nursery.start_soon(_core.enable_ki_protection(raiser), "r1", record)
            # __aexit__ blocks, and then receives the KI

    with pytest.raises(KeyboardInterrupt):
        _core.run(check_protected_kill)
    assert record == {"s1 ok", "s2 ok", "r1 cancel ok"}

    # kill at last moment still raises (run_sync_soon until it raises an
    # error, then kill)
    print("check 3")

    async def check_kill_during_shutdown():
        token = _core.current_trio_token()

        def kill_during_shutdown():
            assert _core.currently_ki_protected()
            try:
                token.run_sync_soon(kill_during_shutdown)
            except _core.RunFinishedError:
                # it's too late for regular handling! handle this!
                print("kill! kill!")
                ki_self()

        token.run_sync_soon(kill_during_shutdown)

    with pytest.raises(KeyboardInterrupt):
        _core.run(check_kill_during_shutdown)

    # KI arrives very early, before main is even spawned
    print("check 4")

    class InstrumentOfDeath:
        def before_run(self):
            ki_self()

    async def main():
        await _core.checkpoint()

    with pytest.raises(KeyboardInterrupt):
        _core.run(main, instruments=[InstrumentOfDeath()])

    # checkpoint_if_cancelled notices pending KI
    print("check 5")

    @_core.enable_ki_protection
    async def main_a() -> None:
        assert _core.currently_ki_protected()
        ki_self()
        with pytest.raises(KeyboardInterrupt):
            await _core.checkpoint_if_cancelled()

    _core.run(main_a)

    # KI arrives while main task is not abortable, b/c already scheduled
    print("check 6")

    @_core.enable_ki_protection
    async def main_b() -> None:
        assert _core.currently_ki_protected()
        ki_self()
        await _core.cancel_shielded_checkpoint()
        await _core.cancel_shielded_checkpoint()
        await _core.cancel_shielded_checkpoint()
        with pytest.raises(KeyboardInterrupt):
            await _core.checkpoint()

    _core.run(main_b)

    # KI arrives while main task is not abortable, b/c refuses to be aborted
    print("check 7")

    @_core.enable_ki_protection
    async def main_c() -> None:
        assert _core.currently_ki_protected()
        ki_self()
        task = _core.current_task()

        def abort(_):
            _core.reschedule(task, outcome.Value(1))
            return _core.Abort.FAILED

        assert await _core.wait_task_rescheduled(abort) == 1
        with pytest.raises(KeyboardInterrupt):
            await _core.checkpoint()

    _core.run(main_c)

    # KI delivered via slow abort
    print("check 8")

    @_core.enable_ki_protection
    async def main_d() -> None:
        assert _core.currently_ki_protected()
        ki_self()
        task = _core.current_task()

        def abort(raise_cancel):
            result = outcome.capture(raise_cancel)
            _core.reschedule(task, result)
            return _core.Abort.FAILED

        with pytest.raises(KeyboardInterrupt):
            assert await _core.wait_task_rescheduled(abort)
        await _core.checkpoint()

    _core.run(main_d)

    # KI arrives just before main task exits, so the run_sync_soon machinery
    # is still functioning and will accept the callback to deliver the KI, but
    # by the time the callback is actually run, main has exited and can't be
    # aborted.
    print("check 9")

    @_core.enable_ki_protection
    async def main_e() -> None:
        ki_self()

    with pytest.raises(KeyboardInterrupt):
        _core.run(main_e)

    print("check 10")
    # KI in unprotected code, with
    # restrict_keyboard_interrupt_to_checkpoints=True
    record = []

    async def main_f():
        # We're not KI protected...
        assert not _core.currently_ki_protected()
        ki_self()
        # ...but even after the KI, we keep running uninterrupted...
        record.append("ok")
        # ...until we hit a checkpoint:
        with pytest.raises(KeyboardInterrupt):
            await sleep(10)

    _core.run(main_f, restrict_keyboard_interrupt_to_checkpoints=True)
    assert record == ["ok"]
    record = []
    # Exact same code raises KI early if we leave off the argument, doesn't
    # even reach the record.append call:
    with pytest.raises(KeyboardInterrupt):
        _core.run(main_f)
    assert record == []

    # KI arrives while main task is inside a cancelled cancellation scope
    # the KeyboardInterrupt should take priority
    print("check 11")

    @_core.enable_ki_protection
    async def main_g() -> None:
        assert _core.currently_ki_protected()
        with _core.CancelScope() as cancel_scope:
            cancel_scope.cancel()
            with pytest.raises(_core.Cancelled):
                await _core.checkpoint()
            ki_self()
            with pytest.raises(KeyboardInterrupt):
                await _core.checkpoint()
            with pytest.raises(_core.Cancelled):
                await _core.checkpoint()

    _core.run(main_g)


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


# Regression test for #461
def test_ki_with_broken_threads() -> None:
    thread = threading.main_thread()

    # scary!
    original = threading._active[thread.ident]  # type: ignore[attr-defined]

    # put this in a try finally so we don't have a chance of cascading a
    # breakage down to everything else
    try:
        del threading._active[thread.ident]  # type: ignore[attr-defined]

        @_core.enable_ki_protection
        async def inner() -> None:
            assert signal.getsignal(signal.SIGINT) != signal.default_int_handler

        _core.run(inner)
    finally:
        threading._active[thread.ident] = original  # type: ignore[attr-defined]


# For details on why this test is non-trivial, see:
#   https://github.com/python-trio/trio/issues/42
#   https://github.com/python-trio/trio/issues/109
@slow
def test_ki_wakes_us_up() -> None:
    assert is_main_thread()

    # This test is flaky due to a race condition on Windows; see:
    #   https://github.com/python-trio/trio/issues/119
    #   https://bugs.python.org/issue30038
    # I think the only fix is to wait for fixed CPython to be released, so in
    # the mean time, on affected versions we send two signals (equivalent to
    # hitting control-C twice). This works because the problem is that the C
    # level signal handler does
    #
    #   write-to-fd -> set-flags
    #
    # and we need
    #
    #   set-flags -> write-to-fd
    #
    # so running the C level signal handler twice does
    #
    #   write-to-fd -> set-flags -> write-to-fd -> set-flags
    #
    # which contains the desired sequence.
    #
    # Affected version of CPython include 3.6.1 and earlier.
    # It's fixed in 3.6.2 and 3.7+
    #
    # PyPy was never affected.
    #
    # The problem technically can occur on Unix as well, if a signal is
    # delivered to a non-main thread, though we haven't observed this in
    # practice.
    #
    # There's also this theoretical problem, but hopefully it won't actually
    # bite us in practice:
    #   https://bugs.python.org/issue31119
    #   https://bitbucket.org/pypy/pypy/issues/2623
    import platform

    buggy_wakeup_fd = (
        sys.version_info < (3, 6, 2) and platform.python_implementation() == "CPython"
    )

    # lock is only needed to avoid an annoying race condition where the
    # *second* ki_self() call arrives *after* the first one woke us up and its
    # KeyboardInterrupt was caught, and then generates a second
    # KeyboardInterrupt that aborts the test run. The kill_soon thread holds
    # the lock while doing the calls to ki_self, which means that it holds it
    # while the C-level signal handler is running. Then in the main thread,
    # when we're woken up we know that ki_self() has been run at least once;
    # if we then take the lock it guaranteeds that ki_self() has been run
    # twice, so if a second KeyboardInterrupt is going to arrive it should
    # arrive by the time we've acquired the lock. This lets us force it to
    # happen inside the pytest.raises block.
    #
    # It will be very nice when the buggy_wakeup_fd bug is fixed.
    lock = threading.Lock()

    def kill_soon():
        # We want the signal to be raised after the main thread has entered
        # the IO manager blocking primitive. There really is no way to
        # deterministically interlock with that, so we have to use sleep and
        # hope it's long enough.
        time.sleep(1.1)
        with lock:
            print("thread doing ki_self()")
            ki_self()
            if buggy_wakeup_fd:
                print("buggy_wakeup_fd =", buggy_wakeup_fd)
                ki_self()

    async def main():
        thread = threading.Thread(target=kill_soon)
        print("Starting thread")
        thread.start()
        try:
            with pytest.raises(KeyboardInterrupt):
                # To limit the damage on CI if this does get broken (as
                # compared to sleep_forever())
                print("Going to sleep")
                try:
                    await sleep(20)
                    print("Woke without raising?!")  # pragma: no cover
                # The only purpose of this finally: block is to soak up the
                # second KeyboardInterrupt that might arrive on
                # buggy_wakeup_fd platforms. So it might get aborted at any
                # moment randomly on some runs, so pragma: no cover avoids
                # coverage flapping:
                finally:  # pragma: no cover
                    print("waiting for lock")
                    with lock:
                        print("got lock")
                    # And then we want to force a PyErr_CheckSignals. Which is
                    # not so easy on Windows. Weird kluge: builtin_repr calls
                    # PyObject_Repr, which does an unconditional
                    # PyErr_CheckSignals for some reason.
                    print(repr(None))
                    # And finally, it's possible that the signal was delivered
                    # but at a moment when we had KI protection enabled, so we
                    # need to execute a checkpoint to ensure it's delivered
                    # before we exit main().
                    await _core.checkpoint()
        finally:
            print("joining thread", sys.exc_info())
            thread.join()

    start = time.perf_counter()
    try:
        _core.run(main)
    finally:
        end = time.perf_counter()
        print("duration", end - start)
        print("sys.exc_info", sys.exc_info())
    assert 1.0 <= (end - start) < 2
