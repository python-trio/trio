# This is a public namespace, so we dont want to expose any non-underscored
# attributes that arent actually part of our public API. But its very
# annoying to carefully always use underscored names for module-level
# temporaries, imports, etc. when implementing the module. So we put the
# implementation in an underscored module, and then re-export the public parts
# here.
# import importlib

from ._socket import *
from ._socket import _stdlib_socket

# from ._socket import __all__
# from ._socket import (gaierror, herror, gethostname, ntohs, htonl, htons, inet_aton, inet_ntoa, inet_pton, inet_ntop, sethostname, if_nameindex, if_nametoindex, if_indextoname, set_custom_hostname_resolver, set_custom_socket_factory, getaddrinfo, getnameinfo, getprotobyname, from_stdlib_socket, fromfd, socketpair, socket, SocketType)

# _sock_module = importlib.import_module('_socket', 'trio')
# globals().update({_name: getattr(_sock_module, _name) for _name in _sock_module.__dict__.keys() if _name.isupper()})


class TrioSocket:
    def __init(self):
        pass


TrioSocket.AF_APPLETALK = _stdlib_socket.AF_APPLETALK

setattr(TrioSocket, 'AF_INET', _stdlib_socket.AF_INET)
