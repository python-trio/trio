import abc

# XX On windows closesocket actually *can* block
#   https://msdn.microsoft.com/en-us/library/ms737582(v=VS.85).aspx
# specifically, if the linger options are set so that it waits for all sent
# data to be acked before closing (this is not the default).
#
# DisconnectEx has a OVERLAPPED mode. the page is not as useful b/c it doesn't
# say why disconnecting might block:
#   https://msdn.microsoft.com/en-us/library/ms737757(VS.85).aspx
# but I guess it's the for the reasons described for closesocket, and it
# provides an IOCP-friendly interface to that.
#
# I'm not sure if this linger thing is worth supporting, but, so we know.
#
# ...Linux has the same thing!
#
# https://www.nybek.com/blog/2015/04/29/so_linger-on-non-blocking-sockets/
#
# ...but maybe there's no way to actually use it from an async program?
# sweet.
#
# lingering is kinda worthless anyway, because what it does it let us tell
# whether our packets reached the peer's TCP stack. But it doesn't tell us
# whether they actually reached disk, or the database, or whatever. Or even
# reached userspace at all. I guess in some exotic userspace TCP
# implementation someone might only ACK after processing the data but...
#
# If we make close sync and then decide we want this, then probably we should
# do is add an async lingering_close, which can use a thread or whatever as
# appropriate for the platform. That's probably a better API anyway than
# having a single method that does different things depending on whether
# you've fiddled with setsockopt.

class Resource(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def close(self):
        # XX docstring should warn that this is a harsh shutdown, so e.g. TLS
        # will be truncated, which you might or might not want.
        pass

    async def __aenter__(self):
        raise TypeError("use regular 'with', not 'async with'")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

class SendStream(Resource):
    @abc.abstractmethod
    async def sendall(self, data):
        pass

    # This is only a hint, because in some cases we don't know (Windows), or
    # we have only a noisy signal (TLS). And in the use cases this is included
    # to account for, returning before it's actually writable is NBD, it just
    # makes them slightly less efficient.
    @abc.abstractmethod
    async def until_maybe_writable(self):
        pass

    @property
    @abc.abstractmethod
    def can_send_eof(self):
        pass

    @abc.abstractmethod
    def send_eof(self):
        pass

class RecvStream(Resource):
    @abc.abstractmethod
    async def recv(self, max_bytes):
        pass

class Stream(SendStream, RecvStream):
    pass
