import pytest

import attr

from ..testing import assert_checkpoints
from .. import abc as tabc


async def test_AsyncResource_defaults():
    @attr.s
    class MyAR(tabc.AsyncResource):
        record = attr.ib(default=attr.Factory(list))

        async def aclose(self):
            self.record.append("ac")

    async with MyAR() as myar:
        assert isinstance(myar, MyAR)
        assert myar.record == []

    assert myar.record == ["ac"]


def test_abc_generics():
    class SomeChannel(tabc.SendChannel[tabc.Stream]):
        def send_nowait(self, value): raise RuntimeError
        async def send(self, value): raise RuntimeError
        def clone(self): raise RuntimeError
        async def aclose(self): pass

    channel = SomeChannel()
    with pytest.raises(RuntimeError):
        channel.send_nowait(None)
