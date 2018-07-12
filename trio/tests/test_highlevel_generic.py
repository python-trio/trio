import pytest

import attr

from ..abc import SendStream, ReceiveStream
from .._highlevel_generic import StapledStream, IterableStream
from ..testing import memory_stream_pair


@attr.s
class RecordSendStream(SendStream):
    record = attr.ib(default=attr.Factory(list))

    async def send_all(self, data):
        self.record.append(("send_all", data))

    async def wait_send_all_might_not_block(self):
        self.record.append("wait_send_all_might_not_block")

    async def aclose(self):
        self.record.append("aclose")


@attr.s
class RecordReceiveStream(ReceiveStream):
    record = attr.ib(default=attr.Factory(list))

    async def receive_some(self, max_bytes):
        self.record.append(("receive_some", max_bytes))

    async def aclose(self):
        self.record.append("aclose")


async def test_StapledStream():
    send_stream = RecordSendStream()
    receive_stream = RecordReceiveStream()
    stapled = StapledStream(send_stream, receive_stream)

    assert stapled.send_stream is send_stream
    assert stapled.receive_stream is receive_stream

    await stapled.send_all(b"foo")
    await stapled.wait_send_all_might_not_block()
    assert send_stream.record == [
        ("send_all", b"foo"),
        "wait_send_all_might_not_block",
    ]
    send_stream.record.clear()

    await stapled.send_eof()
    assert send_stream.record == ["aclose"]
    send_stream.record.clear()

    async def fake_send_eof():
        send_stream.record.append("send_eof")

    send_stream.send_eof = fake_send_eof
    await stapled.send_eof()
    assert send_stream.record == ["send_eof"]

    send_stream.record.clear()
    assert receive_stream.record == []

    await stapled.receive_some(1234)
    assert receive_stream.record == [("receive_some", 1234)]
    assert send_stream.record == []
    receive_stream.record.clear()

    await stapled.aclose()
    assert receive_stream.record == ["aclose"]
    assert send_stream.record == ["aclose"]


async def test_StapledStream_with_erroring_close():
    # Make sure that if one of the aclose methods errors out, then the other
    # one still gets called.
    class BrokenSendStream(RecordSendStream):
        async def aclose(self):
            await super().aclose()
            raise ValueError

    class BrokenReceiveStream(RecordReceiveStream):
        async def aclose(self):
            await super().aclose()
            raise ValueError

    stapled = StapledStream(BrokenSendStream(), BrokenReceiveStream())

    with pytest.raises(ValueError) as excinfo:
        await stapled.aclose()
    assert isinstance(excinfo.value.__context__, ValueError)

    assert stapled.send_stream.record == ["aclose"]
    assert stapled.receive_stream.record == ["aclose"]


async def test_IterableStream_demo():
    sender, receiver = memory_stream_pair()

    iterable_stream = IterableStream(receiver)

    await sender.send_all(b'Hello World!')
    await sender.send_eof()

    assert [72, 101, 108, 108, 111, 32, 87, 111, 114, 108, 100, 33] == [c async for c in iterable_stream]
