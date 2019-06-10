'''
syncronous routines to load/parse a read buffer and utilities to convert
raw bytes into user-specified objects (i.e. memessages)
'''
from os import linesep
from itertools import takewhile

MAX_BUF = 2**14
class BufferOverflow(Exception):
    pass
class FrameError(Exception):
    pass

def deframe(proto, maxbuf=MAX_BUF, **kw_proto):
    '''
    wrapper to bind a protocol to a buffer
    returns a function which accepts raw data an os.linesepd returns iterator of messages that exausts buffer
    '''
    buf = bytearray()
    pos = 0

    def read_exact(sz):
        ''' 
        consumes and returns bytaearray of requested size
        yields None when insufficient buffer
        '''
        nonlocal pos, buf
        while len(buf) < sz:
            yield
        ret = buf[:sz]
        del buf[:sz]
        pos = 0
        return ret
            
    def read_until(sep, stop=None):
        '''
        consumes and returns bytaearray up to requested separator
        separator is consumed but not returned, yields None when insufficient buffer
        '''
        nonlocal pos
        sep_len = len(sep)
        while True:
            i = buf.find(sep, pos, stop)
            if i > -1:
                ret = buf[:i]
                del buf[: i + sep_len]
                pos = 0
                return ret
            if stop and len(buf) > stop:
                raise FrameError
            pos = max(0, len(buf) - sep_len)
            yield
        
    p = proto(read_until, read_exact, **kw_proto)
    
    def is_good(msg):
        return msg is not None

    def append(chunk):
        '''
        add to buffer, return iterator of protocol's results
        filters out None, so returns empty iterator with insufficient buffer
        see examples for intended usage
        '''
        nonlocal buf
        if chunk:
            if len(chunk) + len(buf) > maxbuf:
                raise BufferOverflow(buf)
            buf += chunk
        return takewhile(is_good, p)
    return append

    
def netstring_proto(until, exact, max_msg=9999, **kw_decode):
    max_hdr = len(str(max_msg)) + 1
    while True:
        size_chunk = yield from until(b':', stop=max_hdr)
        size = int(size_chunk)
        if size > max_msg:
            raise FrameError

        body = yield from exact(size+1)
        if body[-1:] !=  b',':
            raise FrameError
        yield body[:-1].decode(**kw_decode)
        
        
def line_proto(read_until, _, delim=linesep.encode(), **kw_ignored):
    while True:
        yield (yield from read_until(delim))
        
        
        
        
        
        

        
        
        
        
        
        