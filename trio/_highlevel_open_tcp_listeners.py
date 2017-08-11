import sys
from math import inf

from ._highlevel_socket import SocketListener
from . import socket as tsocket

__all__ = ["open_tcp_listeners"]


# Default backlog size:
#
# Having the backlog too low can cause practical problems (a perfectly healthy
# service that starts failing to accept connections if they arrive in a
# burst).
#
# Having it too high doesn't really cause any problems. Like any buffer, you
# want backlog queue to be zero usually, and it won't save you if you're
# getting connection attempts faster than you can call accept() on an ongoing
# basis. But unlike other buffers, this one doesn't really provide any
# backpressure. If a connection gets stuck waiting in the backlog queue, then
# from the peer's point of view the connection succeeded but then their
# send/recv will stall until we get to it, possibly for a long time. OTOH if
# there isn't room in the backlog queue... then their connect stalls, possibly
# for a long time, which is pretty much the same thing.
#
# A large backlog can also use a bit more kernel memory, but this seems fairly
# negligible these days.
#
# So this suggests we should make the backlog as large as possible. This also
# matches what Golang does. However, they do it in a weird way, where they
# have a bunch of code to sniff out the configured upper limit for backlog on
# different operating systems. But on every system, passing in a too-large
# backlog just causes it to be silently truncated to the configured maximum,
# so this is unnecessary -- we can just pass in "infinity" and get the maximum
# that way. (Verified on Windows, Linux, MacOS using
# notes-to-self/measure-listen-backlog.py)
def _compute_backlog(backlog):
    if backlog is None:
        backlog = inf
    # Many systems (Linux, BSDs, ...) store the backlog in a uint16 and are
    # missing overflow protection, so we apply our own overflow protection.
    # https://github.com/golang/go/issues/5030
    return min(backlog, 0xffff)


async def open_tcp_listeners(port, *, host=None, backlog=None):
    """Create :class:`SocketListener` objects to listen for TCP connections.

    Args:

      port (int): The port to listen on. If you pass 0, the kernel will
          automatically pick an arbitrary open port. But be careful: if you
          use ``port=0`` when binding to multiple IP address, then each IP
          address will be assigned a different port. An example of when this
          happens is when ``host=None``, which means to bind to both the IPv4
          wildcard address (``0.0.0.0``) and also the IPv6 wildcard address
          (``::``).

      host (str or None): The local interface to bind to. This is passed to
          :func:`~socket.getaddrinfo` with the ``AI_PASSIVE`` flag set.

          If you have a specific interface you want to bind to, pass its IP
          address or hostname here. If a hostname resolves to multiple IP
          addresses, this function will bind one listener to each of them.

          If you want to bind to all available interfaces (the wildcard
          address) for both IPv4 and IPv6, pass ``None`` (the default).

          If you want to use only IPv4, or only IPv6, but want to accept on
          all interfaces, pass the family-specific wildcard address:
          ``"0.0.0.0"`` or ``"::"``.

      backlog (int or None): The listen backlog to use. If you leave this as
          ``None`` then Trio will pick a good default.

    Returns:
      list of :class:`SocketListener`

    """
    backlog = _compute_backlog(backlog)

    addresses = await tsocket.getaddrinfo(
        host,
        port,
        type=tsocket.SOCK_STREAM,
        flags=tsocket.AI_PASSIVE,
    )

    listeners = []
    try:
        for family, type, proto, _, sockaddr in addresses:
            sock = tsocket.socket(family, type, proto)
            try:
                # See https://github.com/python-trio/trio/issues/39
                if sys.platform == "win32":
                    sock.setsockopt(
                        tsocket.SOL_SOCKET, tsocket.SO_EXCLUSIVEADDRUSE, 1
                    )
                else:
                    sock.setsockopt(
                        tsocket.SOL_SOCKET, tsocket.SO_REUSEADDR, 1
                    )

                if family == tsocket.AF_INET6:
                    sock.setsockopt(
                        tsocket.IPPROTO_IPV6, tsocket.IPV6_V6ONLY, 1
                    )

                sock.bind(sockaddr)
                sock.listen(backlog)

                listeners.append(SocketListener(sock))
            except:
                sock.close()
                raise
    except:
        for listener in listeners:
            listener.socket.close()
        raise

    return listeners
