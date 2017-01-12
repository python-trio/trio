import abc

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
