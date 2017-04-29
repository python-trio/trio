import abc
import contextlib

import attr

from . import _core
from .abc import StreamWithSendEOF

__all__ = [
    "StapledStream",
]

@attr.s(slots=True, cmp=False, hash=False)
class StapledStream(StreamWithSendEOF):
    send_stream = attr.ib()
    recv_stream = attr.ib()

    async def sendall(self, data):
        return await self.send_stream.sendall(data)

    async def wait_sendall_might_not_block(self):
        return await self.send_stream.wait_sendall_might_not_block()

    async def send_eof(self):
        if hasattr(self.send_stream.send_eof):
            return await self.send_stream.send_eof()
        else:
            return await self.send_stream.graceful_close()

    async def recv(self, max_bytes):
        return self.recv_stream.recv(max_bytes)

    def forceful_close(self):
        try:
            self.send_stream.forceful_close()
        finally:
            self.recv_stream.forceful_close()

    async def graceful_close(self):
        try:
            await self.send_stream.graceful_close()
        finally:
            await self.recv_stream.graceful_close()
