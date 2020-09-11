import pytest
import asyncio
import contextvars
import sys
import traceback
import queue
from functools import partial
from math import inf
import signal
import socket
import threading
import time
import weakref

from outcome import capture, Value, Error
import trio
import trio.testing
from .tutil import gc_collect_harder, buggy_pypy_asyncgens
from ..._util import signal_raise

# The simplest possible "host" loop.
# Nice features:
# - we can run code "outside" of trio using the schedule function passed to
#   our main
# - final result is returned
# - any unhandled exceptions cause an immediate crash


class TrivialHostLoop:
    def __init__(self, install_asyncgen_hooks=False):
        self.todo = queue.Queue()
        self.host_thread = threading.current_thread()
        self.asyncgens_alive = weakref.WeakSet()
        self.install_asyncgen_hooks = install_asyncgen_hooks

    def call_soon_threadsafe(self, fn):
        if self.host_thread is threading.current_thread():  # pragma: no cover
            crash = partial(
                pytest.fail, "run_sync_soon_threadsafe called from host thread"
            )
            self.todo.put(("run", crash))
        self.todo.put(("run", fn))

    def call_soon_not_threadsafe(self, fn):
        if self.host_thread is not threading.current_thread():  # pragma: no cover
            crash = partial(
                pytest.fail, "run_sync_soon_not_threadsafe called from worker thread"
            )
            self.todo.put(("run", crash))
        self.todo.put(("run", fn))

    def stop(self, outcome):
        self.todo.put(("unwrap", outcome))

    def run(self):
        def firstiter(agen):
            self.asyncgens_alive.add(agen)

        def finalizer(agen):
            def finalize_it():
                with pytest.raises(StopIteration):
                    agen.aclose().send(None)

            self.todo.put(("run", finalize_it))

        prev_hooks = sys.get_asyncgen_hooks()
        install_asyncgen_hooks = self.install_asyncgen_hooks
        if install_asyncgen_hooks:
            sys.set_asyncgen_hooks(firstiter=firstiter, finalizer=finalizer)
        try:
            while True:
                op, obj = self.todo.get()
                if op == "run":
                    obj()
                elif op == "unwrap":
                    # Avoid keeping self.todo alive, since it might contain
                    # a reference to GuestState.guest_tick
                    del self
                    return obj.unwrap()
                else:  # pragma: no cover
                    assert False
        finally:
            if install_asyncgen_hooks:
                sys.set_asyncgen_hooks(*prev_hooks)

    async def host_this_run(self, *, with_buggy_deliver_cancel=False):
        def run_as_child_host(resume_trio_as_guest):
            resume_trio = partial(
                resume_trio_as_guest,
                run_sync_soon_threadsafe=self.call_soon_threadsafe,
                run_sync_soon_not_threadsafe=self.call_soon_not_threadsafe,
            )
            self.todo.put(("run", resume_trio))
            return self.run()

        def deliver_cancel(raise_cancel):
            self.stop(capture(raise_cancel))
            if with_buggy_deliver_cancel:
                raise ValueError("whoops")

        return await trio.lowlevel.become_guest_for(run_as_child_host, deliver_cancel)


def trivial_guest_run(trio_fn, **start_guest_run_kwargs):
    loop = TrivialHostLoop()

    def call_soon(fn):
        loop.call_soon_not_threadsafe(fn)

    trio.lowlevel.start_guest_run(
        trio_fn,
        call_soon,
        run_sync_soon_threadsafe=loop.call_soon_threadsafe,
        run_sync_soon_not_threadsafe=loop.call_soon_not_threadsafe,
        done_callback=loop.stop,
        **start_guest_run_kwargs,
    )
    try:
        return loop.run()
    finally:
        # Make sure that exceptions raised here don't capture these, so that
        # if an exception does cause us to abandon a run then the Trio state
        # has a chance to be GC'ed and warn about it.
        del loop


def test_guest_trivial():
    async def trio_return(in_host):
        await trio.sleep(0)
        return "ok"

    assert trivial_guest_run(trio_return) == "ok"

    async def trio_fail(in_host):
        raise KeyError("whoopsiedaisy")

    with pytest.raises(KeyError, match="whoopsiedaisy"):
        trivial_guest_run(trio_fail)


def test_guest_can_do_io():
    async def trio_main(in_host):
        record = []
        a, b = trio.socket.socketpair()
        with a, b:
            async with trio.open_nursery() as nursery:

                async def do_receive():
                    record.append(await a.recv(1))

                nursery.start_soon(do_receive)
                await trio.testing.wait_all_tasks_blocked()

                await b.send(b"x")

        assert record == [b"x"]

    trivial_guest_run(trio_main)


def test_host_can_directly_wake_trio_task():
    async def trio_main(in_host):
        ev = trio.Event()
        in_host(ev.set)
        await ev.wait()
        return "ok"

    assert trivial_guest_run(trio_main) == "ok"


def test_host_altering_deadlines_wakes_trio_up():
    def set_deadline(cscope, new_deadline):
        cscope.deadline = new_deadline

    async def trio_main(in_host):
        with trio.CancelScope() as cscope:
            in_host(lambda: set_deadline(cscope, -inf))
            await trio.sleep_forever()
        assert cscope.cancelled_caught

        with trio.CancelScope() as cscope:
            # also do a change that doesn't affect the next deadline, just to
            # exercise that path
            in_host(lambda: set_deadline(cscope, 1e6))
            in_host(lambda: set_deadline(cscope, -inf))
            await trio.sleep(999)
        assert cscope.cancelled_caught

        return "ok"

    assert trivial_guest_run(trio_main) == "ok"


def test_warn_set_wakeup_fd_overwrite():
    assert signal.set_wakeup_fd(-1) == -1

    async def trio_main(in_host):
        return "ok"

    a, b = socket.socketpair()
    with a, b:
        a.setblocking(False)

        # Warn if there's already a wakeup fd
        signal.set_wakeup_fd(a.fileno())
        try:
            with pytest.warns(RuntimeWarning, match="signal handling code.*collided"):
                assert trivial_guest_run(trio_main) == "ok"
        finally:
            assert signal.set_wakeup_fd(-1) == a.fileno()

        signal.set_wakeup_fd(a.fileno())
        try:
            with pytest.warns(RuntimeWarning, match="signal handling code.*collided"):
                assert (
                    trivial_guest_run(trio_main, host_uses_signal_set_wakeup_fd=False)
                    == "ok"
                )
        finally:
            assert signal.set_wakeup_fd(-1) == a.fileno()

        # Don't warn if there isn't already a wakeup fd
        with pytest.warns(None) as record:
            assert trivial_guest_run(trio_main) == "ok"
        # Apparently this is how you assert 'there were no RuntimeWarnings'
        with pytest.raises(AssertionError):
            record.pop(RuntimeWarning)

        with pytest.warns(None) as record:
            assert (
                trivial_guest_run(trio_main, host_uses_signal_set_wakeup_fd=True)
                == "ok"
            )
        with pytest.raises(AssertionError):
            record.pop(RuntimeWarning)

        # If there's already a wakeup fd, but we've been told to trust it,
        # then it's left alone and there's no warning
        signal.set_wakeup_fd(a.fileno())
        try:

            async def trio_check_wakeup_fd_unaltered(in_host):
                fd = signal.set_wakeup_fd(-1)
                assert fd == a.fileno()
                signal.set_wakeup_fd(fd)
                return "ok"

            with pytest.warns(None) as record:
                assert (
                    trivial_guest_run(
                        trio_check_wakeup_fd_unaltered,
                        host_uses_signal_set_wakeup_fd=True,
                    )
                    == "ok"
                )
            with pytest.raises(AssertionError):
                record.pop(RuntimeWarning)
        finally:
            assert signal.set_wakeup_fd(-1) == a.fileno()


def test_host_wakeup_doesnt_trigger_wait_all_tasks_blocked():
    # This is designed to hit the branch in unrolled_run where:
    #   idle_primed=True
    #   runner.runq is empty
    #   events is Truth-y
    # ...and confirm that in this case, wait_all_tasks_blocked does not get
    # triggered.
    def set_deadline(cscope, new_deadline):
        print(f"setting deadline {new_deadline}")
        cscope.deadline = new_deadline

    async def trio_main(in_host):
        async def sit_in_wait_all_tasks_blocked(watb_cscope):
            with watb_cscope:
                # Overall point of this test is that this
                # wait_all_tasks_blocked should *not* return normally, but
                # only by cancellation.
                await trio.testing.wait_all_tasks_blocked(cushion=9999)
                assert False  # pragma: no cover
            assert watb_cscope.cancelled_caught

        async def get_woken_by_host_deadline(watb_cscope):
            with trio.CancelScope() as cscope:
                print("scheduling stuff to happen")
                # Altering the deadline from the host, to something in the
                # future, will cause the run loop to wake up, but then
                # discover that there is nothing to do and go back to sleep.
                # This should *not* trigger wait_all_tasks_blocked.
                #
                # So the 'before_io_wait' here will wait until we're blocking
                # with the wait_all_tasks_blocked primed, and then schedule a
                # deadline change. The critical test is that this should *not*
                # wake up 'sit_in_wait_all_tasks_blocked'.
                #
                # The after we've had a chance to wake up
                # 'sit_in_wait_all_tasks_blocked', we want the test to
                # actually end. So in after_io_wait we schedule a second host
                # call to tear things down.
                class InstrumentHelper:
                    def __init__(self):
                        self.primed = False

                    def before_io_wait(self, timeout):
                        print(f"before_io_wait({timeout})")
                        if timeout == 9999:  # pragma: no branch
                            assert not self.primed
                            in_host(lambda: set_deadline(cscope, 1e9))
                            self.primed = True

                    def after_io_wait(self, timeout):
                        if self.primed:  # pragma: no branch
                            print("instrument triggered")
                            in_host(lambda: cscope.cancel())
                            trio.lowlevel.remove_instrument(self)

                trio.lowlevel.add_instrument(InstrumentHelper())
                await trio.sleep_forever()
            assert cscope.cancelled_caught
            watb_cscope.cancel()

        async with trio.open_nursery() as nursery:
            watb_cscope = trio.CancelScope()
            nursery.start_soon(sit_in_wait_all_tasks_blocked, watb_cscope)
            await trio.testing.wait_all_tasks_blocked()
            nursery.start_soon(get_woken_by_host_deadline, watb_cscope)

        return "ok"

    assert trivial_guest_run(trio_main) == "ok"


def test_guest_warns_if_abandoned():
    # This warning is emitted from the garbage collector. So we have to make
    # sure that our abandoned run is garbage. The easiest way to do this is to
    # put it into a function, so that we're sure all the local state,
    # traceback frames, etc. are garbage once it returns.
    def do_abandoned_guest_run():
        async def abandoned_main(in_host):
            in_host(lambda: 1 / 0)
            while True:
                await trio.sleep(0)

        with pytest.raises(ZeroDivisionError):
            trivial_guest_run(abandoned_main)

    with pytest.warns(RuntimeWarning, match="Trio guest run got abandoned"):
        do_abandoned_guest_run()
        gc_collect_harder()

        # If you have problems some day figuring out what's holding onto a
        # reference to the unrolled_run generator and making this test fail,
        # then this might be useful to help track it down. (It assumes you
        # also hack start_guest_run so that it does 'global W; W =
        # weakref(unrolled_run_gen)'.)
        #
        # import gc
        # print(trio._core._run.W)
        # targets = [trio._core._run.W()]
        # for i in range(15):
        #     new_targets = []
        #     for target in targets:
        #         new_targets += gc.get_referrers(target)
        #         new_targets.remove(targets)
        #     print("#####################")
        #     print(f"depth {i}: {len(new_targets)}")
        #     print(new_targets)
        #     targets = new_targets

        with pytest.raises(RuntimeError):
            trio.current_time()


def aiotrio_run(trio_fn, *, pass_not_threadsafe=True, **start_guest_run_kwargs):
    loop = asyncio.new_event_loop()

    async def aio_main():
        trio_done_fut = asyncio.Future()

        def trio_done_callback(main_outcome):
            print(f"trio_fn finished: {main_outcome!r}")
            trio_done_fut.set_result(main_outcome)

        if pass_not_threadsafe:
            start_guest_run_kwargs["run_sync_soon_not_threadsafe"] = loop.call_soon

        trio.lowlevel.start_guest_run(
            trio_fn,
            run_sync_soon_threadsafe=loop.call_soon_threadsafe,
            done_callback=trio_done_callback,
            **start_guest_run_kwargs,
        )

        return (await trio_done_fut).unwrap()

    try:
        return loop.run_until_complete(aio_main())
    finally:
        loop.close()


def test_guest_mode_on_asyncio():
    async def trio_main():
        print("trio_main!")

        to_trio, from_aio = trio.open_memory_channel(float("inf"))
        from_trio = asyncio.Queue()

        aio_task = asyncio.ensure_future(aio_pingpong(from_trio, to_trio))

        # Make sure we have at least one tick where we don't need to go into
        # the thread
        await trio.sleep(0)

        from_trio.put_nowait(0)

        async for n in from_aio:
            print(f"trio got: {n}")
            from_trio.put_nowait(n + 1)
            if n >= 10:
                aio_task.cancel()
                return "trio-main-done"

    async def aio_pingpong(from_trio, to_trio):
        print("aio_pingpong!")

        try:
            while True:
                n = await from_trio.get()
                print(f"aio got: {n}")
                to_trio.send_nowait(n + 1)
        except asyncio.CancelledError:
            raise
        except:  # pragma: no cover
            traceback.print_exc()
            raise

    assert (
        aiotrio_run(
            trio_main,
            # Not all versions of asyncio we test on can actually be trusted,
            # but this test doesn't care about signal handling, and it's
            # easier to just avoid the warnings.
            host_uses_signal_set_wakeup_fd=True,
        )
        == "trio-main-done"
    )

    assert (
        aiotrio_run(
            trio_main,
            # Also check that passing only call_soon_threadsafe works, via the
            # fallback path where we use it for everything.
            pass_not_threadsafe=False,
            host_uses_signal_set_wakeup_fd=True,
        )
        == "trio-main-done"
    )


def test_guest_mode_internal_errors(monkeypatch, recwarn):
    with monkeypatch.context() as m:

        async def crash_in_run_loop(in_host):
            m.setattr("trio._core._run.GLOBAL_RUN_CONTEXT.runner.runq", "HI")
            await trio.sleep(1)

        with pytest.raises(trio.TrioInternalError):
            trivial_guest_run(crash_in_run_loop)

    with monkeypatch.context() as m:

        async def crash_in_io(in_host):
            m.setattr("trio._core._run.TheIOManager.get_events", None)
            await trio.sleep(0)

        with pytest.raises(trio.TrioInternalError):
            trivial_guest_run(crash_in_io)

    with monkeypatch.context() as m:

        async def crash_in_worker_thread_io(in_host):
            t = threading.current_thread()
            old_get_events = trio._core._run.TheIOManager.get_events

            def bad_get_events(*args):
                if threading.current_thread() is not t:
                    raise ValueError("oh no!")
                else:
                    return old_get_events(*args)

            m.setattr("trio._core._run.TheIOManager.get_events", bad_get_events)

            await trio.sleep(1)

        with pytest.raises(trio.TrioInternalError):
            trivial_guest_run(crash_in_worker_thread_io)

    gc_collect_harder()


def test_guest_mode_ki():
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler

    # Check SIGINT in Trio func and in host func
    async def trio_main(in_host):
        with pytest.raises(KeyboardInterrupt):
            signal_raise(signal.SIGINT)

        # Host SIGINT should get injected into Trio
        in_host(partial(signal_raise, signal.SIGINT))
        await trio.sleep(10)

    with pytest.raises(KeyboardInterrupt) as excinfo:
        trivial_guest_run(trio_main)
    assert excinfo.value.__context__ is None
    # Signal handler should be restored properly on exit
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler

    # Also check chaining in the case where KI is injected after main exits
    final_exc = KeyError("whoa")

    async def trio_main_raising(in_host):
        in_host(partial(signal_raise, signal.SIGINT))
        raise final_exc

    with pytest.raises(KeyboardInterrupt) as excinfo:
        trivial_guest_run(trio_main_raising)
    assert excinfo.value.__context__ is final_exc

    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def test_guest_mode_autojump_clock_threshold_changing():
    # This is super obscure and probably no-one will ever notice, but
    # technically mutating the MockClock.autojump_threshold from the host
    # should wake up the guest, so let's test it.

    clock = trio.testing.MockClock()

    DURATION = 120

    async def trio_main(in_host):
        assert trio.current_time() == 0
        in_host(lambda: setattr(clock, "autojump_threshold", 0))
        await trio.sleep(DURATION)
        assert trio.current_time() == DURATION

    start = time.monotonic()
    trivial_guest_run(trio_main, clock=clock)
    end = time.monotonic()
    # Should be basically instantaneous, but we'll leave a generous buffer to
    # account for any CI weirdness
    assert end - start < DURATION / 2


@pytest.mark.skipif(buggy_pypy_asyncgens, reason="PyPy 7.2 is buggy")
def test_guest_mode_aio_asyncgens():
    import sniffio

    record = set()

    async def agen(label):
        assert sniffio.current_async_library() == label
        try:
            yield 1
        finally:
            library = sniffio.current_async_library()
            try:
                await sys.modules[library].sleep(0)
            except trio.Cancelled:
                pass
            record.add((label, library))

    async def iterate_in_aio():
        # "trio" gets inherited from our Trio caller if we don't set this
        sniffio.current_async_library_cvar.set("asyncio")
        await agen("asyncio").asend(None)

    async def trio_main():
        task = asyncio.ensure_future(iterate_in_aio())
        done_evt = trio.Event()
        task.add_done_callback(lambda _: done_evt.set())
        with trio.fail_after(1):
            await done_evt.wait()

        await agen("trio").asend(None)

        gc_collect_harder()

    # Ensure we don't pollute the thread-level context if run under
    # an asyncio without contextvars support (3.6)
    context = contextvars.copy_context()
    context.run(aiotrio_run, trio_main, host_uses_signal_set_wakeup_fd=True)

    assert record == {("asyncio", "asyncio"), ("trio", "trio")}


async def test_become_guest_basics():
    def run_noop_child_host(resume_trio_guest):
        return 42

    def ignore_cxl(_):
        pass  # pragma: no cover

    assert 42 == await trio.lowlevel.become_guest_for(run_noop_child_host, ignore_cxl)
    assert isinstance(
        trio.lowlevel.current_task()._runner.asyncgens.alive, weakref.WeakSet
    )

    loop = TrivialHostLoop()
    loop.stop(Value(5))
    assert 5 == await loop.host_this_run()
    assert isinstance(
        trio.lowlevel.current_task()._runner.asyncgens.alive, weakref.WeakSet
    )

    async with trio.open_nursery() as nursery:

        @nursery.start_soon
        async def stop_soon():
            await trio.testing.wait_all_tasks_blocked()
            loop.stop(Value(10))

        assert 10 == await loop.host_this_run()

    loop.stop(Error(KeyError("hi")))
    with pytest.raises(KeyError, match="hi"):
        await loop.host_this_run()


async def test_become_guest_cancel(autojump_clock):
    loop = TrivialHostLoop()
    with trio.move_on_after(1) as cancel_scope:
        await loop.host_this_run()
    assert cancel_scope.cancelled_caught


async def test_cant_become_guest_twice():
    loop = TrivialHostLoop()
    async with trio.open_nursery() as nursery:
        nursery.start_soon(loop.host_this_run)
        await trio.testing.wait_all_tasks_blocked()

        with pytest.raises(RuntimeError, match="is already a guest"):
            await loop.host_this_run()

        nursery.cancel_scope.cancel()


async def test_become_asyncio_guest():
    loop = asyncio.get_event_loop()
    to_trio, from_aio = trio.open_memory_channel(float("inf"))
    from_trio = asyncio.Queue()

    async def aio_pingpong(from_trio, to_trio):
        print("aio_pingpong!")

        try:
            while True:
                n = await from_trio.get()
                print(f"aio got: {n}")
                to_trio.send_nowait(n + 1)
        except asyncio.CancelledError:
            return "aio-done"
        except:  # pragma: no cover
            traceback.print_exc()
            raise

    aio_task = asyncio.ensure_future(aio_pingpong(from_trio, to_trio))

    def run_aio_child_host(resume_trio_as_guest):
        # Test without a _not_threadsafe callback in order to exercise that path
        resume_trio_as_guest(run_sync_soon_threadsafe=loop.call_soon_threadsafe)
        return loop.run_until_complete(aio_task)

    def deliver_cancel(_):
        loop.stop()  # pragma: no cover

    async with trio.open_nursery() as nursery:

        @nursery.start_soon
        async def become_guest_and_check_result():
            assert "aio-done" == await trio.lowlevel.become_guest_for(
                run_aio_child_host, deliver_cancel
            )

        # Make sure we have at least one tick where we don't need to go into
        # the thread
        await trio.sleep(0)

        from_trio.put_nowait(0)

        async for n in from_aio:
            print(f"trio got: {n}")
            from_trio.put_nowait(n + 1)
            if n >= 10:
                aio_task.cancel()
                return "trio-main-done"


def test_become_guest_propagates_TrioInternalError(recwarn):
    async def main():
        with trio.move_on_after(1):
            loop = TrivialHostLoop()
            await loop.host_this_run(with_buggy_deliver_cancel=True)

    with pytest.raises(trio.TrioInternalError) as info:
        trio.run(main, clock=trio.testing.MockClock(autojump_threshold=0))

    assert isinstance(info.value.__cause__, ValueError)
    assert str(info.value.__cause__) == "whoops"

    del info
    gc_collect_harder()


def test_become_guest_raises_TrioInternalError_if_run_completes(recwarn):
    for outcome in (Value(42), Error(ValueError("lol"))):

        async def main():
            async with trio.open_nursery() as nursery:
                loop = TrivialHostLoop(install_asyncgen_hooks=True)
                nursery.start_soon(loop.host_this_run)
                await trio.testing.wait_all_tasks_blocked()

                runner = trio._core._run.GLOBAL_RUN_CONTEXT.runner
                runner.tasks.clear()
                runner.main_task_outcome = outcome

                # That will make the runner exit as soon as we yield,
                # but the host loop won't notice unless we poke it.
                loop.stop(None)

        with pytest.raises(trio.TrioInternalError, match="before child host") as info:
            trio.run(main)
        assert repr(outcome) in str(info.value)
        if isinstance(outcome, Error):
            assert info.value.__cause__ is outcome.error
        # Make sure we correctly restored the outermost asyncgen hooks
        # (the ones that existed before trio.run() started)
        assert sys.get_asyncgen_hooks() == (None, None)

    del info
    gc_collect_harder()


def test_become_guest_failure(recwarn):
    async def main():
        def break_parent(resume_trio_as_guest):
            class TrappingGuestState(trio._core._run.GuestState):
                __slots__ = ()

                @property
                def run_sync_soon_threadsafe(self):
                    raise ValueError("gotcha")

            sys._getframe(2).f_locals["guest_state"].__class__ = TrappingGuestState

        def ignore_cancel(_):
            pass  # pragma: no cover

        await trio.lowlevel.become_guest_for(break_parent, ignore_cancel)

    with pytest.raises(trio.TrioInternalError, match="do_become_guest.*failed") as info:
        trio.run(main)

    assert isinstance(info.value.__cause__, ValueError)
    assert str(info.value.__cause__) == "gotcha"

    del info
    gc_collect_harder()


def test_become_guest_asyncgens():
    record = set()

    def canary_firstiter(agen):  # pragma: no cover
        record.add("canary_firstiter")
        pytest.fail("outside-of-trio async generator hook was invoked")

    async def trio_agen():
        try:
            yield 1
        finally:
            # Make sure Trio finalizer works
            trio.lowlevel.current_task()
            with pytest.raises(trio.Cancelled):
                await trio.sleep(0)
            record.add("trio_agen")

    async def host_loop_agen(started_evt):
        started_evt.set()
        try:
            yield 1
        finally:
            # Make sure foreign finalizer works
            with pytest.raises(RuntimeError):
                trio.lowlevel.current_task()
            record.add("host_loop_agen")

    def step(agen):
        with pytest.raises(StopIteration):
            agen.asend(None).send(None)

    async def trio_main():
        loop = TrivialHostLoop(install_asyncgen_hooks=True)
        started_evt = trio.Event()
        ag_host = host_loop_agen(started_evt)
        ag_trio = trio_agen()

        async with trio.open_nursery() as nursery:
            nursery.start_soon(loop.host_this_run)
            await trio.testing.wait_all_tasks_blocked()

            assert ag_host not in loop.asyncgens_alive
            loop.todo.put(("run", partial(step, ag_host)))
            await started_evt.wait()
            assert ag_host in loop.asyncgens_alive  # foreign firstiter works

            trio_asyncgens_alive = trio.lowlevel.current_task()._runner.asyncgens.alive
            assert ag_trio not in trio_asyncgens_alive
            step(ag_trio)
            assert ag_trio in trio_asyncgens_alive  # trio firstiter works

            del ag_host
            del ag_trio
            gc_collect_harder()

            nursery.cancel_scope.cancel()

    prev_hooks = sys.get_asyncgen_hooks()
    sys.set_asyncgen_hooks(firstiter=canary_firstiter, finalizer=None)
    try:
        trio.run(trio_main)
        assert sys.get_asyncgen_hooks() == (canary_firstiter, None)
        assert record == {"trio_agen", "host_loop_agen"}
    finally:
        sys.set_asyncgen_hooks(*prev_hooks)


def test_become_guest_during_asyncgen_finalization():
    saved = []
    record = []

    async def agen():
        try:
            yield 1
        finally:
            with trio.CancelScope(shield=True) as scope, trio.fail_after(1):
                loop = TrivialHostLoop(install_asyncgen_hooks=True)
                loop.todo.put(("run", scope.cancel))
                await loop.host_this_run()
            assert isinstance(trio.lowlevel.current_task()._runner.asyncgens.alive, set)
            record.append("ok")

    async def main():
        saved.append(agen())
        await saved[-1].asend(None)

    trio.run(main)
    assert record == ["ok"]
