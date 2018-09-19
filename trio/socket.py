# This is a public namespace, so we dont want to expose any non-underscored
# attributes that arent actually part of our public API. But its very
# annoying to carefully always use underscored names for module-level
# temporaries, imports, etc. when implementing the module. So we put the
# implementation in an underscored module, and then re-export the public parts
# here.
import sys as _sys
from socket import *
from ._socket import *
