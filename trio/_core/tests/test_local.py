import pytest
from functools import partial

from ... import _core


# scary runvar tests
def test_runvar_smoketest():
    t1 = _core.RunVar("test1")
    t2 = _core.RunVar("test2", default="catfish")

    assert "RunVar" in repr(t1)

    async def first_check():
        with pytest.raises(LookupError):
            t1.get()

        t1.set("swordfish")
        assert t1.get() == "swordfish"
        assert t2.get() == "catfish"
        assert t2.get(default="eel") == "eel"

        t2.set("goldfish")
        assert t2.get() == "goldfish"
        assert t2.get(default="tuna") == "goldfish"

    async def second_check():
        with pytest.raises(LookupError):
            t1.get()

        assert t2.get() == "catfish"

    _core.run(first_check)
    _core.run(second_check)


def test_runvar_resetting():
    t1 = _core.RunVar("test1")
    t2 = _core.RunVar("test2", default="dogfish")
    t3 = _core.RunVar("test3")

    async def reset_check():
        token = t1.set("moonfish")
        assert t1.get() == "moonfish"
        t1.reset(token)

        with pytest.raises(TypeError):
            t1.reset(None)

        with pytest.raises(LookupError):
            t1.get()

        token2 = t2.set("catdogfish")
        assert t2.get() == "catdogfish"
        t2.reset(token2)
        assert t2.get() == "dogfish"

        with pytest.raises(ValueError):
            t2.reset(token2)

        token3 = t3.set("basculin")
        assert t3.get() == "basculin"

        with pytest.raises(ValueError):
            t1.reset(token3)

    _core.run(reset_check)


def test_runvar_sync():
    t1 = _core.RunVar("test1")

    async def sync_check():
        async def task1():
            t1.set("plaice")
            assert t1.get() == "plaice"

        async def task2(tok):
            t1.reset(token)

            with pytest.raises(LookupError):
                t1.get()

            t1.set("cod")

        async with _core.open_nursery() as n:
            token = t1.set("cod")
            assert t1.get() == "cod"

            n.start_soon(task1)
            await _core.wait_all_tasks_blocked()
            assert t1.get() == "plaice"

            n.start_soon(task2, token)
            await _core.wait_all_tasks_blocked()
            assert t1.get() == "cod"

    _core.run(sync_check)


def test_accessing_runvar_outside_run_call_fails():
    t1 = _core.RunVar("test1")

    with pytest.raises(RuntimeError):
        t1.set("asdf")

    with pytest.raises(RuntimeError):
        t1.get()

    async def get_token():
        return t1.set("ok")

    token = _core.run(get_token)

    with pytest.raises(RuntimeError):
        t1.reset(token)


async def test_treevar():
    tv1 = _core.TreeVar("tv1")
    tv2 = _core.TreeVar("tv2", default=None)
    assert tv1.name == "tv1"
    assert "TreeVar name='tv2'" in repr(tv2)

    with pytest.raises(LookupError):
        tv1.get()
    assert tv2.get() is None
    assert tv1.get(42) == 42
    assert tv2.get(42) == 42

    NOTHING = object()

    async def should_be(val1, val2, new1=NOTHING):
        assert tv1.get(NOTHING) == val1
        assert tv2.get(NOTHING) == val2
        if new1 is not NOTHING:
            tv1.set(new1)

    tok1 = tv1.set(10)
    async with _core.open_nursery() as outer:
        tok2 = tv1.set(15)
        with tv2.being(20):
            assert tv2.get_in(_core.current_task()) == 20
            async with _core.open_nursery() as inner:
                tv1.reset(tok2)
                outer.start_soon(should_be, 10, NOTHING, 100)
                inner.start_soon(should_be, 15, 20, 200)
                await _core.wait_all_tasks_blocked()
                assert tv1.get_in(_core.current_task()) == 10
                await should_be(10, 20, 300)
                assert tv1.get_in(inner) == 15
                assert tv1.get_in(outer) == 10
                assert tv1.get_in(_core.current_task()) == 300
                assert tv2.get_in(inner) == 20
                assert tv2.get_in(outer) is None
                assert tv2.get_in(_core.current_task()) == 20
                tv1.reset(tok1)
                await should_be(NOTHING, 20)
                assert tv1.get_in(inner) == 15
                assert tv1.get_in(outer) == 10
                with pytest.raises(LookupError):
                    assert tv1.get_in(_core.current_task())
        assert tv2.get() is None
        assert tv2.get_in(_core.current_task()) is None


async def test_treevar_follows_eventual_parent():
    tv1 = _core.TreeVar("tv1")

    def trivial_abort(_):
        return _core.Abort.SUCCEEDED  # pragma: no cover

    async def manage_target(task_status):
        assert tv1.get() == "source nursery"
        with tv1.being("target nursery"):
            assert tv1.get() == "target nursery"
            async with _core.open_nursery() as target_nursery:
                with tv1.being("target nested child"):
                    assert tv1.get() == "target nested child"
                    task_status.started(target_nursery)
                    await _core.wait_task_rescheduled(trivial_abort)
                    assert tv1.get() == "target nested child"
                assert tv1.get() == "target nursery"
            assert tv1.get() == "target nursery"
        assert tv1.get() == "source nursery"

    async def verify(value, *, task_status=_core.TASK_STATUS_IGNORED):
        assert tv1.get() == value
        task_status.started()
        assert tv1.get() == value

    with tv1.being("source nursery"):
        async with _core.open_nursery() as source_nursery:
            with tv1.being("source->target start call"):
                target_nursery = await source_nursery.start(manage_target)
            with tv1.being("verify task"):
                source_nursery.start_soon(verify, "source nursery")
                target_nursery.start_soon(verify, "target nursery")
                await source_nursery.start(verify, "source nursery")
                await target_nursery.start(verify, "target nursery")
            _core.reschedule(target_nursery.parent_task)


async def test_treevar_token_bound_to_task_that_obtained_it():
    tv1 = _core.TreeVar("tv1")
    token = None

    async def get_token():
        nonlocal token
        token = tv1.set(10)
        try:
            await _core.wait_task_rescheduled(lambda _: _core.Abort.SUCCEEDED)
        finally:
            tv1.reset(token)
            with pytest.raises(LookupError):
                tv1.get()
            with pytest.raises(LookupError):
                tv1.get_in(_core.current_task())

    async with _core.open_nursery() as nursery:
        nursery.start_soon(get_token)
        await _core.wait_all_tasks_blocked()
        assert token is not None
        with pytest.raises(ValueError, match="different Context"):
            tv1.reset(token)
        assert tv1.get_in(list(nursery.child_tasks)[0]) == 10
        nursery.cancel_scope.cancel()


def test_treevar_outside_run():
    async def run_sync(fn, *args):
        return fn(*args)

    tv1 = _core.TreeVar("tv1", default=10)
    for operation in (
        tv1.get,
        partial(tv1.get, 20),
        partial(tv1.set, 30),
        lambda: tv1.reset(_core.run(run_sync, tv1.set, 10)),
        tv1.being(40).__enter__,
    ):
        with pytest.raises(RuntimeError, match="must be called from async context"):
            operation()
