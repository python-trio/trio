import sys
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
            assert "example" in _core.current_task().name
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
