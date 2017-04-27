import pytest

import signal

from .._util import *
from .. import _core
from ..testing import wait_all_tasks_blocked

def test_signal_raise():
    record = []
    def handler(signum, _):
        record.append(signum)

    old = signal.signal(signal.SIGFPE, handler)
    try:
        signal_raise(signal.SIGFPE)
    finally:
        signal.signal(signal.SIGFPE, old)
    assert record == [signal.SIGFPE]


async def test_UnLock():
    ul1 = UnLock(RuntimeError, "ul1")
    ul2 = UnLock(ValueError)

    with ul1:
        with ul2:
            print("ok")

    with pytest.raises(RuntimeError) as excinfo:
        with ul1:
            with ul1:
                pass  # pragma: no cover
    assert "ul1" in str(excinfo.value)

    with pytest.raises(ValueError) as excinfo:
        with ul2:
            with ul2:
                pass  # pragma: no cover

    async def wait_with_ul1():
        with ul1:
            await wait_all_tasks_blocked()

    with pytest.raises(RuntimeError) as excinfo:
        async with _core.open_nursery() as nursery:
            nursery.spawn(wait_with_ul1)
            nursery.spawn(wait_with_ul1)
    assert "ul1" in str(excinfo.value)
