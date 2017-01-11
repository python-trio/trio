import abc

# SSL shutdown:
# - call unwrap() on the SSLSocket/SSLObject
# - this sends the "all done here" SSL message
# - but in many practical applications this is neither sent nor checked for,
#   e.g. HTTPS usually ignores it:
#   https://security.stackexchange.com/questions/82028/ssl-tls-is-a-server-always-required-to-respond-to-a-close-notify
#   BUT it is important in some cases, so should be possible to handle
#   properly.
#
# I think the answer is: close is synchronous, and the TLS Stream also has an
# async def unwrap() which sends the close_notify message.
# Possibly we should also default suppress_ragged_eofs to False, unlike the
# stdlib? not sure.

class WriteStream(metaclass=abc.ABCMeta):
    # This is only a hint, because in some cases we don't know (Windows), or
    # we have only a noisy signal (TLS). And in the use cases this is included
    # to account for, returning before it's actually writable is NBD, it just
    # makes them slightly less efficient.
    @abc.abstractmethod
    async def until_maybe_writable(self):
        pass

    @abc.abstractmethod
    async def sendall(self, data):
        pass

    @abc.abstractmethod
    def can_send_eof(self):
        pass

    @abc.abstractmethod
    def send_eof(self):
        pass

    @abc.abstractmethod
    def close(self):
        pass

class ReadStream(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def recv(self, max_bytes):
        pass

    @abc.abstractmethod
    def close(self):
        pass

class Stream(ReadStream, WriteStream):
    pass
