# This is a public namespace, so we dont want to expose any non-underscored
# attributes that arent actually part of our public API. But its very
# annoying to carefully always use underscored names for module-level
# temporaries, imports, etc. when implementing the module. So we put the
# implementation in an underscored module, and then re-export the public parts
# here.
import importlib
import socket

#from ._socket import *
#from ._socket import __all__
#import _socket as socket
from ._socket import (gaierror, herror, gethostname, ntohs, htonl, htons, inet_aton, inet_ntoa, inet_pton, inet_ntop, sethostname, if_nameindex, if_nametoindex, if_indextoname, set_custom_hostname_resolver, set_custom_socket_factory, getaddrinfo, getnameinfo, getprotobyname, from_stdlib_socket, fromfd, socketpair, socket, SocketType)

_sock_module = importlib.import_module('_socket')
print(_sock_module.__dict__)
globals().update({_name: getattr(_sock_module, _name) for _name in [_uname for _uname in _sock_module.__dict__ if _uname.isupper()]})

AF_APPLETALK = socket.AF_APPLETALK

