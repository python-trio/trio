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
