import pytest

import attr

from ..testing import assert_yields
from .. import abc as tabc

async def test_AsyncResource_defaults():
    @attr.s
    class MyAR(tabc.AsyncResource):
        record = attr.ib(default=attr.Factory(list))

        def forceful_close(self):
            self.record.append("fc")

    async with MyAR() as myar:
        assert isinstance(myar, MyAR)
        assert myar.record == []

    assert myar.record == ["fc"]

    with assert_yields():
        await myar.graceful_close()
    assert myar.record == ["fc", "fc"]

    @attr.s
    class BadAR(tabc.AsyncResource):
        record = attr.ib(default=attr.Factory(list))

        def forceful_close(self):
            self.record.append("boom")
            raise KeyError

    badar = BadAR()
    with pytest.raises(KeyError):
        with assert_yields():
            await badar.graceful_close()
    assert badar.record == ["boom"]
