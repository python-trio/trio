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
    "current_clock":
        _deprecate.DeprecatedAttribute(
            hazmat.current_clock, "0.2.0", issue=317
        ),
    "current_statistics":
        _deprecate.DeprecatedAttribute(
            hazmat.current_statistics, "0.2.0", issue=317
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
