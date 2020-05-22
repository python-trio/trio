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


async def test_scopevar():
    sv1 = _core.ScopeVar("sv1")
    sv2 = _core.ScopeVar("sv2", default=None)
    with pytest.raises(LookupError):
        sv1.get()
    assert sv2.get() is None
    assert sv1.get(42) == 42
    assert sv2.get(42) == 42

    NOTHING = object()

    async def should_be(val1, val2, new1=NOTHING):
        assert sv1.get(NOTHING) == val1
        assert sv2.get(NOTHING) == val2
        if new1 is not NOTHING:
            sv1.set(new1)

    tok1 = sv1.set(10)
    async with _core.open_nursery() as outer:
        tok2 = sv1.set(15)
        with sv2.being(20):
            assert sv2.get_in(_core.current_task()) == 20
            async with _core.open_nursery() as inner:
                sv1.reset(tok2)
                outer.start_soon(should_be, 10, NOTHING, 100)
                inner.start_soon(should_be, 15, 20, 200)
                await _core.wait_all_tasks_blocked()
                assert sv1.get_in(_core.current_task()) == 10
                await should_be(10, 20, 300)
                assert sv1.get_in(inner) == 15
                assert sv1.get_in(outer) == 10
                assert sv1.get_in(_core.current_task()) == 300
                assert sv2.get_in(inner) == 20
                assert sv2.get_in(outer) is None
                assert sv2.get_in(_core.current_task()) == 20
                sv1.reset(tok1)
                await should_be(NOTHING, 20)
                assert sv1.get_in(inner) == 15
                assert sv1.get_in(outer) == 10
                with pytest.raises(LookupError):
                    assert sv1.get_in(_core.current_task())
        assert sv2.get() is None
        assert sv2.get_in(_core.current_task()) is None


async def test_scopevar_token_bound_to_task_that_obtained_it():
    sv1 = _core.ScopeVar("sv1")
    token = None

    async def get_token():
        nonlocal token
        token = sv1.set(10)
        try:
            await _core.wait_task_rescheduled(lambda _: _core.Abort.SUCCEEDED)
        finally:
            sv1.reset(token)
            with pytest.raises(LookupError):
                sv1.get()
            with pytest.raises(LookupError):
                sv1.get_in(_core.current_task())

    async with _core.open_nursery() as nursery:
        nursery.start_soon(get_token)
        await _core.wait_all_tasks_blocked()
        assert token is not None
        with pytest.raises(ValueError, match="different Context"):
            sv1.reset(token)
        assert sv1.get_in(list(nursery.child_tasks)[0]) == 10
        nursery.cancel_scope.cancel()


def test_scopevar_outside_run():
    async def run_sync(fn, *args):
        return fn(*args)

    sv1 = _core.ScopeVar("sv1", default=10)
    for operation in (
        sv1.get,
        partial(sv1.get, 20),
        partial(sv1.set, 30),
        lambda: sv1.reset(_core.run(run_sync, sv1.set, 10)),
        sv1.being(40).__enter__,
    ):
        with pytest.raises(RuntimeError, match="must be called from async context"):
            operation()
