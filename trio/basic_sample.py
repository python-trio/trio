#!/usr/bin/env python3
#import attr
import trio

from ._basic_proto import deframe, netstring_proto

PORT = 12345
CHUNK = 2**12

class NetstringChan(trio.abc.ReceiveChannel):
    def __init__(self, receive_stream):
        self.stream = receive_stream
        self.get_msgs = deframe(netstring_proto)
        self.msgs = iter([])
        
    def receive_nowait(self):
        try:
            next(self.msgs)
        except StopIteration:
            raise trio.WouldBlock
        
    async def aclose(self):
        pass
    
    async def receive(self):
        try:
            return next(self.msgs)
        except StopIteration:
            while True:
                m = self.get_msgs(await self.stream.receive_some(CHUNK))
                self.msgs = m
                try:
                    return next(self.msgs)
                except StopIteration:
                    pass  # proto needs more chunks
    
    def clone(self):
        pass   
#        while True:
#            for m in get_msgs(self.stream.receive_some(CHUNK)):
                
#    @trio._util.aiter_compat
#    def __aiter__(self):
#        return self
    
#    async def __anext__(self):


     

        
#
#async def a_main():
##    client_stream = await trio.open_tcp_stream("127.0.0.1", PORT)
#    rcv_chan = NetstringChan(None)
#    rcv_chan.receive_nowait
#    
#    
#trio.run(a_main)

    
import pytest
import trio.testing

@pytest.fixture
def make_chan():
    mrs = trio.testing.MemoryReceiveStream()
    return NetstringChan(mrs)

def test_empty(make_chan):
#    chan = make_chan
    with pytest.raises(trio.WouldBlock):
        print(make_chan.receive_nowait())
   
pytest.main()
     
#def test_one():



