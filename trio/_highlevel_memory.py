# "High-level" in-memory networking interface

from . import _core, sleep, open_memory_channel, StapledStream
from ._sync import Event, Queue
from .abc import HalfCloseableStream, Listener

__all__ = ["memory_connect", "MemoryStream", "MemoryListener"]

from . import testing

# An efficient way to communicate between :
# - coroutines ? -> TODO perf
# - eventloops ? -> TODO perf
# - threads ? -> TODO perf
# - processes ? -> TODO perf
#: List of channels (one per endpoint) to communicate client streams after connection has been accepted
memory_endpoints = {}


async def memory_connect(endpoint):
    # we might need to wait for the endpoint to appear in the dict
    rec_chan = memory_endpoints.get(endpoint)
    while rec_chan is None:
        await sleep(.1)

    return await rec_chan[1].receive()

MemoryStream = StapledStream


################################################################
# InProcListener
################################################################


class MemoryListener(Listener):

    def __init__(self, endpoint, accept_hook=None):
        self.accept_hook = accept_hook
        self.accepted_streams = list()
        self.endpoint = endpoint
        memory_endpoints[self.endpoint] = open_memory_channel(1)
        self.closed = False

    async def accept(self):
        await _core.checkpoint()
        if self.closed:
            raise _core.ClosedResourceError(self)
        if self.accept_hook is not None:
            await self.accept_hook()

        client, server = testing.memory_stream_pair()
        await memory_endpoints[self.endpoint][0].send(client)
        self.accepted_streams.append(server)
        return server

    async def aclose(self):
        self.closed = True
        await _core.checkpoint()


