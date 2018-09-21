# This is a public namespace, so we dont want to expose any non-underscored
# attributes that arent actually part of our public API. But its very
# annoying to carefully always use underscored names for module-level
# temporaries, imports, etc. when implementing the module. So we put the
# implementation in an underscored module, and then re-export the public parts
# here.
import importlib

_smod = importlib.import_module('._socket', 'trio')

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
    if_nametoindex,
    if_indextoname,
)

try:
    from ._socket import sethostname
except ImportError:
    pass

try:
    from ._socket import if_nameindex
except ImportError:
    pass

globals().update({_name: getattr(_smod, _name) for _name in _smod.__dict__})
