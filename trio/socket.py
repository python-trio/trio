# This is a public namespace, so we dont want to expose any non-underscored
# attributes that arent actually part of our public API. But its very
# annoying to carefully always use underscored names for module-level
# temporaries, imports, etc. when implementing the module. So we put the
# implementation in an underscored module, and then re-export the public parts
# here.

from ._socket import (
    fromfd, from_stdlib_socket, getprotobyname, socketpair, getnameinfo,
    socket, getaddrinfo, set_custom_hostname_resolver,
    set_custom_socket_factory, real_socket_type, SocketType, fspath,
    run_sync_in_worker_thread
)

try:
    from ._socket import fromshare
except ImportError:
    pass

from ._socket import (
    gaierror,
    herror,
    gethostname,
    ntohs,
    htonl,
    htons,
    inet_aton,
    inet_ntoa,
    inet_pton,
    inet_ntop,
    sethostname,
    if_nameindex,
    if_nametoindex,
    if_indextoname,
)

from ._socket import (
    SO_REUSEADDR, IPPROTO_SCTP, IPPROTO_IPV6, TCP_NOTSENT_LOWAT
)
#from ._socket import *

from ._socket import (
    AF_INET, AF_INET6, IPPROTO_TCP, SOCK_STREAM, SOL_SOCKET, TCP_NODELAY,
    AI_CANONNAME, MSG_PEEK, IPV6_V6ONLY, SHUT_WR, SOCK_DGRAM, NI_NUMERICHOST,
    AI_PASSIVE, SO_ACCEPTCONN, AF_UNSPEC, SHUT_RD, NI_NUMERICSERV, IPPROTO_UDP,
    SHUT_RDWR, EAI_SOCKTYPE, EAI_BADHINTS, AF_UNIX
)

# from socket import *
