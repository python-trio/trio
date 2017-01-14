@classmethod
def from_stdlib_socket(cls, sock):
    if type(sock) is not stdlib_socket.socket:
        # For example, ssl.SSLSocket subclasses socket.socket, but we
        # certainly don't want to blindly wrap one of those.
        raise TypeError(
            "expected object of type 'socket.socket', not '{}"
            .format(type(sock).__name__))
