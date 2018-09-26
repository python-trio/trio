# This is a public namespace, so we don't want to expose any non-underscored
# attributes that aren't actually part of our public API. But it's very
# annoying to carefully always use underscored names for module-level
# temporaries, imports, etc. when implementing the module. So we put the
# implementation in an underscored module, and then re-export the public parts
# here.
# We still have some underscore names though but only a few.

from . import _socket
import sys as _sys

# import the overwrites
from ._socket import (
    fromfd, from_stdlib_socket, getprotobyname, socketpair, getnameinfo,
    socket, getaddrinfo, set_custom_hostname_resolver,
    set_custom_socket_factory, SocketType
)

# not always available so expose only if
try:
    from ._socket import fromshare
except ImportError:
    pass

# expose these functions to trio.socket
from socket import (
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
)

# not always available so expose only if
try:
    from socket import (
        sethostname, if_nameindex, if_nametoindex, if_indextoname
    )
except ImportError:
    pass

# expose all uppercase names from standardlib socket to trio.socket
import socket as _stdlib_socket

globals().update(
    {
        _name: getattr(_stdlib_socket, _name)
        for _name in _stdlib_socket.__dict__ if _name.isupper()
    }
)

if _sys.platform == 'win32':
    # See https://github.com/python-trio/trio/issues/39
    # Do not import for windows platform
    # (you can still get it from stdlib socket, of course, if you want it)
    del SO_REUSEADDR

# get names used by trio that we define on our own
from ._socket import IPPROTO_IPV6

# Not defined in all python versions and platforms but sometimes needed
try:
    TCP_NOTSENT_LOWAT
except NameError:
    # Hopefully will show up in 3.7:
    #   https://github.com/python/cpython/pull/477
    if _sys.platform == "darwin":
        TCP_NOTSENT_LOWAT = 0x201
    elif _sys.platform == "linux":
        TCP_NOTSENT_LOWAT = 25
