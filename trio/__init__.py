# General layout:
#
# trio/_core/... is the self-contained core library. It does various
# shenanigans to export a consistent "core API", but parts of the core API are
# too low-level to be recommended for regular use. These are marked by having
# a _hazmat=True attribute.
#
# trio/*.py define a set of more usable tools on top of this. They import from
# trio._core and from each other.
#
# This file pulls together the friendly public API, by re-exporting the more
# innocuous bits of the _core API + the the tools from trio/*.py. No-one
# imports it internally; it's only for public consumption. When re-exporting
# _core here, we check for the _hazmat=True attribute and shunt things into
# either our namespace or the hazmat namespace accordingly.

__all__ = []

from ._version import __version__

from . import hazmat

from . import _core
for _symbol in _core.__all__:
    _value = getattr(_core, _symbol)
    if getattr(_value, "_hazmat", False):
        setattr(hazmat, _symbol, _value)
        hazmat.__all__.append(_symbol)
    else:
        globals()[_symbol] = _value
        __all__.append(_symbol)
del _symbol, _value

from ._timeouts import *
__all__ += _timeouts.__all__

from ._sync import *
__all__ += _sync.__all__

from ._threads import *
__all__ += _threads.__all__

from ._streams import *
__all__ += _streams.__all__

from ._signals import *
__all__ += _signals.__all__

# Imported by default
from . import socket
from . import abc
# Not imported by default: testing
