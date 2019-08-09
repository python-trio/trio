import pytest

import attr

import trio
from ..testing import assert_checkpoints
from .. import abc as tabc


async def test_AsyncResource_defaults():
    @attr.s
    class MyAR(tabc.AsyncResource):
        record = attr.ib(factory=list)

        async def aclose(self):
            self.record.append("ac")

    async with MyAR() as myar:
        assert isinstance(myar, MyAR)
        assert myar.record == []

    assert myar.record == ["ac"]


def test_abc_generics():
    # Pythons below 3.5.2 had a typing.Generic that would throw
    # errors when instantiating or subclassing a parameterized
    # version of a class with any __slots__. This is why RunVar
    # (which has slots) is not generic. This tests that
    # the generic ABCs are fine, because while they are slotted
    # they don't actually define any slots.

    class SlottedChannel(tabc.SendChannel[tabc.Stream]):
        __slots__ = ("x",)

        def send_nowait(self, value):
            raise RuntimeError

        async def send(self, value):
            raise RuntimeError  # pragma: no cover

        def clone(self):
            raise RuntimeError  # pragma: no cover

        async def aclose(self):
            pass  # pragma: no cover

    channel = SlottedChannel()
    with pytest.raises(RuntimeError):
        channel.send_nowait(None)


async def test_Stream_send_eof_deprecation():
    # An old-style concrete subclass stream with no send_eof issues a warning
    # at definition time, and a default implementation is filled in
    with pytest.warns(trio.TrioDeprecationWarning, match="send_eof"):
        class OldStyleStream(tabc.Stream):
            async def aclose(self):
                pass

            async def send_all(self, data):
                pass

            async def receive_some(self, max_nbytes=None):
                pass

            async def wait_send_all_might_not_block(self):
                pass

    oss = OldStyleStream()
    with pytest.raises(NotImplementedError):
        await oss.send_eof()

    # But you can still define new abstract subclasses if you want, without
    # getting a warning
    class NewStyleAbstractStreamSubinterface(tabc.Stream):
        async def some_other_method(self):
            pass
