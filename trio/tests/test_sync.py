import pytest

from ..testing import wait_run_loop_idle

from .. import _core
from .._sync import *

async def test_Event():
    e = Event()
    assert not e.is_set()
    assert e.statistics().tasks_waiting == 0

    e.set()
    assert e.is_set()
    await e.wait()

    e.clear()
    assert not e.is_set()

    record = []
    async def child():
        record.append("sleeping")
        await e.wait()
        record.append("woken")

    t1 = await _core.spawn(child)
    t2 = await _core.spawn(child)
    await wait_run_loop_idle()
    assert record == ["sleeping", "sleeping"]
    assert e.statistics().tasks_waiting == 2
    e.set()
    await wait_run_loop_idle()
    assert record == ["sleeping", "sleeping", "woken", "woken"]
