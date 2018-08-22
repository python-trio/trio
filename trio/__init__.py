"""Trio - Pythonic async I/O for humans and snake people.
"""

# General layout:
#
# trio/_core/... is the self-contained core library. It does various
# shenanigans to export a consistent "core API", but parts of the core API are
# too low-level to be recommended for regular use.
#
# trio/*.py define a set of more usable tools on top of this. They import from
# trio._core and from each other.
#
# This file pulls together the friendly public API, by re-exporting the more
# innocuous bits of the _core API + the higher-level tools from trio/*.py.

from ._version import __version__

__all__ = []

from ._toplevel_core_reexports import *
__all__ += _toplevel_core_reexports.__all__

from ._timeouts import *
__all__ += _timeouts.__all__

from ._sync import *
__all__ += _sync.__all__

from ._threads import *
__all__ += _threads.__all__

from ._highlevel_generic import *
__all__ += _highlevel_generic.__all__

from ._signals import *
__all__ += _signals.__all__

from ._highlevel_socket import *
__all__ += _highlevel_socket.__all__

from ._file_io import *
__all__ += _file_io.__all__

from ._path import *
__all__ += _path.__all__

from ._highlevel_serve_listeners import *
__all__ += _highlevel_serve_listeners.__all__

from ._highlevel_open_tcp_stream import *
__all__ += _highlevel_open_tcp_stream.__all__

from ._highlevel_open_tcp_listeners import *
__all__ += _highlevel_open_tcp_listeners.__all__

from ._highlevel_open_unix_stream import *
__all__ += _highlevel_open_unix_stream.__all__

from ._highlevel_pipes import *
__all__ += _highlevel_pipes.__all__

from ._highlevel_ssl_helpers import *
__all__ += _highlevel_ssl_helpers.__all__

from ._deprecate import *
__all__ += _deprecate.__all__

# Imported by default
from . import hazmat
from . import socket
from . import abc
from . import ssl
# Not imported by default: testing

_deprecate.enable_attribute_deprecations(__name__)
__deprecated_attributes__ = {
    "ClosedStreamError":
        _deprecate.DeprecatedAttribute(
            ClosedResourceError,
            "0.5.0",
            issue=36,
            instead=ClosedResourceError
        ),
    "ClosedListenerError":
        _deprecate.DeprecatedAttribute(
            ClosedResourceError,
            "0.5.0",
            issue=36,
            instead=ClosedResourceError
        ),
}

_deprecate.enable_attribute_deprecations(hazmat.__name__)

# Temporary hack to make sure _result is loaded, just during the deprecation
# period
from ._core import _result

hazmat.__deprecated_attributes__ = {
    "Result":
        _deprecate.DeprecatedAttribute(
            _core._result.Result,
            "0.5.0",
            issue=494,
            instead="outcome.Outcome"
        ),
    "Value":
        _deprecate.DeprecatedAttribute(
            _core._result.Value, "0.5.0", issue=494, instead="outcome.Value"
        ),
    "Error":
        _deprecate.DeprecatedAttribute(
            _core._result.Error, "0.5.0", issue=494, instead="outcome.Error"
        )
}

# Having the public path in .__module__ attributes is important for:
# - exception names in printed tracebacks
# - sphinx :show-inheritance:
# - deprecation warnings
# - pickle
# - probably other stuff
from ._util import fixup_module_metadata
fixup_module_metadata(__name__, globals())
fixup_module_metadata(hazmat.__name__, hazmat.__dict__)
fixup_module_metadata(socket.__name__, socket.__dict__)
fixup_module_metadata(abc.__name__, abc.__dict__)
fixup_module_metadata(ssl.__name__, ssl.__dict__)
del fixup_module_metadata
