# This is a public namespace, so we don't want to expose any non-underscored
# attributes that aren't actually part of our public API. But it's very
# annoying to carefully always use underscored names for module-level
# temporaries, imports, etc. when implementing the module. So we put the
# implementation in an underscored module, and then re-export the public parts
# here.
from ._socket import *
from ._socket import __all__

from . import _deprecate
from ._socket import _SocketType
_deprecate.enable_attribute_deprecations(__name__)
__deprecated_attributes__ = {
    "SocketType":
        _deprecate.DeprecatedAttribute(
            _SocketType, "0.2.0", issue=170, instead="is_trio_socket"
        )
}
del _deprecate, _SocketType
