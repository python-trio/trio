import pytest

import threading
import queue

from ... import _core
from ...testing import Sequencer


async def test_local_smoketest(recwarn):
    for cls in _core.TaskLocal, _core.RunLocal:
        local = cls()

        assert local.__dict__ == {}
        assert vars(local) == {}
        assert dir(local) == []
        assert not hasattr(local, "a")

        local.a = 1
        assert local.a == 1
        assert local.__dict__ == {"a": 1}
        assert vars(local) == {"a": 1}
        assert dir(local) == ["a"]
        assert hasattr(local, "a")

        del local.a

        with pytest.raises(AttributeError):
            local.a
        with pytest.raises(AttributeError):
            del local.a

        assert local.__dict__ == {}
        assert vars(local) == {}

        local.__dict__["b"] = 2
        assert local.b == 2

        async def child():
            assert local.b == 2

        async with _core.open_nursery() as nursery:
            nursery.start_soon(child)


async def test_local_isolation(recwarn):
    tlocal = _core.TaskLocal()
    rlocal = _core.RunLocal()

    tlocal.a = "task root"
    rlocal.a = "run root"

    seq = Sequencer()

    async def child1():
        async with seq(0):
            assert tlocal.a == "task root"
            assert rlocal.a == "run root"

            tlocal.a = "task child1"
            rlocal.a = "run child1"

        async with seq(2):
            assert tlocal.a == "task child1"
            assert rlocal.a == "run child2"

    async def child2():
        async with seq(1):
            assert tlocal.a == "task root"
            assert rlocal.a == "run child1"

            tlocal.a = "task child2"
            rlocal.a = "run child2"

    async with _core.open_nursery() as nursery:
        nursery.start_soon(child1)
        nursery.start_soon(child2)

    assert tlocal.a == "task root"
    assert rlocal.a == "run child2"


def test_run_local_multiple_runs(recwarn):
    r = _core.RunLocal()

    async def main(x):
        assert not hasattr(r, "attr")
        r.attr = x
        assert hasattr(r, "attr")
        assert r.attr == x

    # Nothing spills over from one run to the next
    _core.run(main, 1)
    _core.run(main, 2)


def test_run_local_simultaneous_runs(recwarn):
    r = _core.RunLocal()

    result_q = queue.Queue()

    async def main(x, in_q, out_q):
        in_q.get()
        assert not hasattr(r, "attr")
        r.attr = x
        assert hasattr(r, "attr")
        assert r.attr == x
        out_q.put(None)
        in_q.get()
        assert r.attr == x

    def harness(x, in_q, out_q):
        result_q.put(_core.Result.capture(_core.run, main, x, in_q, out_q))

    in_q1 = queue.Queue()
    out_q1 = queue.Queue()
    t1 = threading.Thread(target=harness, args=(1, in_q1, out_q1))
    t1.start()

    in_q2 = queue.Queue()
    out_q2 = queue.Queue()
    t2 = threading.Thread(target=harness, args=(2, in_q2, out_q2))
    t2.start()

    in_q1.put(None)
    out_q1.get()

    in_q2.put(None)
    out_q2.get()

    in_q1.put(None)
    in_q2.put(None)
    t1.join()
    t2.join()
    result_q.get().unwrap()
    result_q.get().unwrap()

    with pytest.raises(RuntimeError):
        r.attr


def test_local_outside_run(recwarn):
    for cls in _core.RunLocal, _core.TaskLocal:
        local = cls()

        with pytest.raises(RuntimeError):
            local.a = 1

        with pytest.raises(RuntimeError):
            dir(local)


async def test_local_inheritance_from_spawner_not_supervisor(recwarn):
    t = _core.TaskLocal()

    t.x = "supervisor"

    async def spawner(nursery):
        t.x = "spawner"
        nursery.start_soon(child)

    async def child():
        assert t.x == "spawner"

    async with _core.open_nursery() as nursery:
        nursery.start_soon(spawner, nursery)


async def test_local_defaults(recwarn):
    for cls in _core.TaskLocal, _core.RunLocal:
        local = cls(default1=123, default2="abc")
        assert local.default1 == 123
        assert local.default2 == "abc"
        del local.default1
        assert not hasattr(local, "default1")


# scary runvar tests
def test_runvar_sanity():
    t1 = _core.RunVar("test1")
    t2 = _core.RunVar("test2", default="catfish")

    async def sanity_check():
        with pytest.raises(LookupError):
            t1.get()

        # sanity checks, first
        t1.set("swordfish")
        assert t1.get() == "swordfish"
        assert t2.get() == "catfish"
        assert t2.get(default="eel") == "eel"

        t2.set("goldfish")
        assert t2.get() == "goldfish"
        assert t2.get(default="tuna") == "goldfish"

    _core.run(sanity_check)


def test_runvar_resetting():
    t1 = _core.RunVar("test1")
    t2 = _core.RunVar("test2", default="dogfish")
    t3 = _core.RunVar("test3")

    async def reset_check():
        token = t1.set("moonfish")
        assert t1.get() == "moonfish"
        t1.reset(token)

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
