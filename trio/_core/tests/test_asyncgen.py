import sys
import weakref
import pytest
from math import inf
from functools import partial
from async_generator import aclosing
from ... import _core
from .tutil import gc_collect_harder


def test_asyncgen_basics():
    collected = []

    async def example(cause):
        try:
            try:
                yield 42
            except GeneratorExit:
                pass
            await _core.checkpoint()
        except _core.Cancelled:
            assert "exhausted" not in cause
            task_name = _core.current_task().name
            assert cause in task_name or task_name == "<init>"
            assert _core.current_effective_deadline() == -inf
            with pytest.raises(_core.Cancelled):
                await _core.checkpoint()
            collected.append(cause)
        else:
            assert "async_main" in _core.current_task().name
            assert "exhausted" in cause
            assert _core.current_effective_deadline() == inf
            await _core.checkpoint()
            collected.append(cause)

    saved = []

    async def async_main():
        # GC'ed before exhausted
        with pytest.warns(
            ResourceWarning, match="Async generator.*collected before.*exhausted",
        ):
            async for val in example("abandoned"):
                assert val == 42
                break
            gc_collect_harder()
        await _core.wait_all_tasks_blocked()
        assert collected.pop() == "abandoned"

        # aclosing() ensures it's cleaned up at point of use
        async with aclosing(example("exhausted 1")) as aiter:
            async for val in aiter:
                assert val == 42
                break
        assert collected.pop() == "exhausted 1"

        # Also fine if you exhaust it at point of use
        async for val in example("exhausted 2"):
            assert val == 42
        assert collected.pop() == "exhausted 2"

        gc_collect_harder()

        # No problems saving the geniter when using either of these patterns
        async with aclosing(example("exhausted 3")) as aiter:
            saved.append(aiter)
            async for val in aiter:
                assert val == 42
                break
        assert collected.pop() == "exhausted 3"

        # Also fine if you exhaust it at point of use
        saved.append(example("exhausted 4"))
        async for val in saved[-1]:
            assert val == 42
        assert collected.pop() == "exhausted 4"

        # Leave one referenced-but-unexhausted and make sure it gets cleaned up
        saved.append(example("outlived run"))
        async for val in saved[-1]:
            assert val == 42
            break
        assert collected == []

    _core.run(async_main)
    assert collected.pop() == "outlived run"
    for agen in saved:
        assert agen.ag_frame is None  # all should now be exhausted


def test_firstiter_after_closing():
    saved = []
    record = []

    async def funky_agen():
        try:
            yield 1
        except GeneratorExit:
            record.append("cleanup 1")
            raise
        try:
            yield 2
        finally:
            record.append("cleanup 2")
            async for _ in funky_agen():
                break

    async def async_main():
        aiter = funky_agen()
        saved.append(aiter)
        assert 1 == await aiter.asend(None)
        assert 2 == await aiter.asend(None)

    _core.run(async_main)
    assert record == ["cleanup 2", "cleanup 1"]


def test_interdependent_asyncgen_cleanup_order():
    saved = []
    record = []

    async def innermost():
        try:
            yield 1
        finally:
            await _core.cancel_shielded_checkpoint()
            record.append("innermost")

    async def agen(label, inner):
        try:
            yield await inner.asend(None)
        finally:
            # Either `inner` has already been cleaned up, or
            # we're about to exhaust it. Either way, we wind
            # up with `record` containing the labels in
            # innermost-to-outermost order.
            with pytest.raises(StopAsyncIteration):
                await inner.asend(None)
            record.append(label)

    async def async_main():
        # This makes a chain of 101 interdependent asyncgens:
        # agen(99)'s cleanup will iterate agen(98)'s will iterate
        # ... agen(0)'s will iterate innermost()'s
        ag_chain = innermost()
        for idx in range(100):
            ag_chain = agen(idx, ag_chain)
        saved.append(ag_chain)
        async for val in ag_chain:
            assert val == 1
            break
        assert record == []

    _core.run(async_main)
    assert record == ["innermost"] + list(range(100))


def test_last_minute_gc_edge_case():
    saved = []
    record = []
    needs_retry = True

    async def agen():
        try:
            yield 1
        finally:
            record.append("cleaned up")

    def collect_at_opportune_moment(token):
        runner = _core._run.GLOBAL_RUN_CONTEXT.runner
        if runner.system_nursery._closed and isinstance(runner.asyncgens, weakref.WeakSet):
            saved.clear()
            record.append("final collection")
            gc_collect_harder()
            record.append("done")
        else:
            try:
                token.run_sync_soon(collect_at_opportune_moment, token)
            except _core.RunFinishedError:
                nonlocal needs_retry
                needs_retry = True

    async def async_main():
        token = _core.current_trio_token()
        token.run_sync_soon(collect_at_opportune_moment, token)
        saved.append(agen())
        async for _ in saved[-1]:
            break

    # Actually running into the edge case requires that the run_sync_soon task
    # execute in between the system nursery's closure and the strong-ification
    # of runner.asyncgens. There's about a 25% chance that it doesn't
    # (if the run_sync_soon task runs before init on one tick and after init
    # on the next tick); if we try enough times, we can make the chance of
    # failure as small as we want.
    for attempt in range(50):
        needs_retry = False
        del record[:]
        del saved[:]
        _core.run(async_main)
        if needs_retry:
            assert record == ["cleaned up"]
        else:
            assert record == ["final collection", "done", "cleaned up"]
            break
    else:
        pytest.fail(
            f"Didn't manage to hit the trailing_finalizer_asyncgens case "
            f"despite trying {attempt} times"
        )
