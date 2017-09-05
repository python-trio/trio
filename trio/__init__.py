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

# PyCharm tries to statically infer the set of attributes of this module, so
# that it can offer completions. (Other IDEs probably do similar things.)
#
# Specifically, it seems to need to see:
#   __all__ = ["some_name"]
# or
#   __all__.append("some_name")
# or
#   from ... import some_name
# or an actual definition of 'some_name'. (See
# https://github.com/python-trio/trio/issues/314 for details.)
#
# _core's exports use all kinds of wacky runtime tricks to set up their
# exports, and then they get divided between trio, trio.hazmat, and
# trio.testing. In an attempt to make this easier to understand for static
# analysis, we now list the re-exports directly here and in trio.hazmat and
# trio.testing, and then we have a test to make sure that every _core export
# does get re-exported in one of these places or another.
__all__ = [
    "TrioInternalError", "RunFinishedError", "WouldBlock", "Cancelled",
    "ResourceBusyError", "MultiError", "format_exception", "run",
    "open_nursery", "open_cancel_scope", "current_effective_deadline",
    "STATUS_IGNORED", "current_time", "current_instruments", "current_clock",
    "remove_instrument", "add_instrument", "current_statistics", "TaskLocal"
]

from . import _core

globals().update({sym: getattr(_core, sym) for sym in __all__})

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

# Stuff that got moved:
_deprecate.enable_attribute_deprecations(__name__)

__deprecated_attributes__ = {
    "Task":
        _deprecate.DeprecatedAttribute(hazmat.Task, "0.2.0", issue=136),
    "current_task":
        _deprecate.DeprecatedAttribute(
            hazmat.current_task, "0.2.0", issue=136
        ),
    "Result":
        _deprecate.DeprecatedAttribute(hazmat.Result, "0.2.0", issue=136),
    "Value":
        _deprecate.DeprecatedAttribute(hazmat.Value, "0.2.0", issue=136),
    "Error":
        _deprecate.DeprecatedAttribute(hazmat.Error, "0.2.0", issue=136),
    "UnboundedQueue":
        _deprecate.DeprecatedAttribute(
            hazmat.UnboundedQueue, "0.2.0", issue=136
        ),
    "run_in_worker_thread":
        _deprecate.DeprecatedAttribute(
            run_sync_in_worker_thread, "0.2.0", issue=68
        ),
}

_deprecate.enable_attribute_deprecations(hazmat.__name__)

hazmat.__deprecated_attributes__ = {
    "yield_briefly":
        _deprecate.DeprecatedAttribute(hazmat.checkpoint, "0.2.0", issue=157),
    "yield_briefly_no_cancel":
        _deprecate.DeprecatedAttribute(
            hazmat.cancel_shielded_checkpoint, "0.2.0", issue=157
        ),
    "yield_if_cancelled":
        _deprecate.DeprecatedAttribute(
            hazmat.checkpoint_if_cancelled, "0.2.0", issue=157
        ),
    "yield_indefinitely":
        _deprecate.DeprecatedAttribute(
            hazmat.wait_task_rescheduled, "0.2.0", issue=157
        ),
}

# Having the public path in .__module__ attributes is important for:
# - exception names in printed tracebacks
# - sphinx :show-inheritance:
# - pickle
# - probably other stuff
from ._util import fixup_module_metadata
fixup_module_metadata(__name__, globals())
fixup_module_metadata(hazmat.__name__, hazmat.__dict__)
fixup_module_metadata(socket.__name__, socket.__dict__)
fixup_module_metadata(abc.__name__, abc.__dict__)
fixup_module_metadata(ssl.__name__, ssl.__dict__)
del fixup_module_metadata
