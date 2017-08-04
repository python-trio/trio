import pytest

import attr

from ..abc import SendStream, ReceiveStream
from .._streams import StapledStream


@attr.s
class RecordSendStream(SendStream):
    record = attr.ib(default=attr.Factory(list))

    async def send_all(self, data):
        self.record.append(("send_all", data))

    async def wait_send_all_might_not_block(self):
        self.record.append("wait_send_all_might_not_block")

    async def graceful_close(self):
        self.record.append("graceful_close")

    def forceful_close(self):
        self.record.append("forceful_close")


@attr.s
class RecordReceiveStream(ReceiveStream):
    record = attr.ib(default=attr.Factory(list))

    async def receive_some(self, max_bytes):
        self.record.append(("receive_some", max_bytes))

    async def graceful_close(self):
        self.record.append("graceful_close")

    def forceful_close(self):
        self.record.append("forceful_close")


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
    assert send_stream.record == ["graceful_close"]
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

    await stapled.graceful_close()
    stapled.forceful_close()
    assert receive_stream.record == ["graceful_close", "forceful_close"]
    assert send_stream.record == ["graceful_close", "forceful_close"]


async def test_StapledStream_with_erroring_close():
    class BrokenSendStream(RecordSendStream):
        def forceful_close(self):
            super().forceful_close()
            raise KeyError

        async def graceful_close(self):
            await super().graceful_close()
            raise ValueError

    class BrokenReceiveStream(RecordReceiveStream):
        def forceful_close(self):
            super().forceful_close()
            raise KeyError

        async def graceful_close(self):
            await super().graceful_close()
            raise ValueError

    stapled = StapledStream(BrokenSendStream(), BrokenReceiveStream())

    with pytest.raises(KeyError) as excinfo:
        stapled.forceful_close()
    assert isinstance(excinfo.value.__context__, KeyError)

    with pytest.raises(ValueError) as excinfo:
        await stapled.graceful_close()
    assert isinstance(excinfo.value.__context__, ValueError)

    assert stapled.send_stream.record == ["forceful_close", "graceful_close"]
    assert stapled.receive_stream.record == [
        "forceful_close", "graceful_close"
    ]
