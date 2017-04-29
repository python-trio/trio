import pytest

import attr

from ..abc import SendStream, RecvStream
from .._streams import StapledStream

@attr.s
class RecordSendStream(SendStream):
    record = attr.ib(default=attr.Factory(list))

    async def sendall(self, data):
        self.record.append(("sendall", data))

    async def wait_sendall_might_not_block(self):
        self.record.append("wait_sendall_might_not_block")

    async def graceful_close(self):
        self.record.append("graceful_close")

    def forceful_close(self):
        self.record.append("forceful_close")


@attr.s
class RecordRecvStream(RecvStream):
    record = attr.ib(default=attr.Factory(list))

    async def recv(self, max_bytes):
        self.record.append(("recv", max_bytes))

    async def graceful_close(self):
        self.record.append("graceful_close")

    def forceful_close(self):
        self.record.append("forceful_close")


async def test_StapledStream():
    send_stream = RecordSendStream()
    recv_stream = RecordRecvStream()
    stapled = StapledStream(send_stream, recv_stream)

    assert stapled.send_stream is send_stream
    assert stapled.recv_stream is recv_stream

    await stapled.sendall(b"foo")
    await stapled.wait_sendall_might_not_block()
    assert send_stream.record == [
        ("sendall", b"foo"), "wait_sendall_might_not_block",
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
    assert recv_stream.record == []

    await stapled.recv(1234)
    assert recv_stream.record == [("recv", 1234)]
    assert send_stream.record == []
    recv_stream.record.clear()

    await stapled.graceful_close()
    stapled.forceful_close()
    assert recv_stream.record == ["graceful_close", "forceful_close"]
    assert send_stream.record == ["graceful_close", "forceful_close"]


async def test_StapledStream_with_erroring_close():
    class BrokenSendStream(RecordSendStream):
        def forceful_close(self):
            super().forceful_close()
            raise KeyError

        async def graceful_close(self):
            await super().graceful_close()
            raise ValueError

    class BrokenRecvStream(RecordRecvStream):
        def forceful_close(self):
            super().forceful_close()
            raise KeyError

        async def graceful_close(self):
            await super().graceful_close()
            raise ValueError

    stapled = StapledStream(BrokenSendStream(), BrokenRecvStream())

    with pytest.raises(KeyError) as excinfo:
        stapled.forceful_close()
    assert isinstance(excinfo.value.__context__, KeyError)

    with pytest.raises(ValueError) as excinfo:
        await stapled.graceful_close()
    assert isinstance(excinfo.value.__context__, ValueError)

    assert stapled.send_stream.record == ["forceful_close", "graceful_close"]
    assert stapled.recv_stream.record == ["forceful_close", "graceful_close"]
