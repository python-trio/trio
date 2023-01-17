"""Trio - A friendly Python library for async concurrency and I/O
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

# Submodules imported by default
from . import abc, from_thread, lowlevel, socket, to_thread
from ._channel import MemoryReceiveChannel, MemorySendChannel, open_memory_channel
from ._core import (
    TASK_STATUS_IGNORED,
    BrokenResourceError,
    BusyResourceError,
    Cancelled,
    CancelScope,
    ClosedResourceError,
    EndOfChannel,
    Nursery,
    RunFinishedError,
    TrioInternalError,
    WouldBlock,
    current_effective_deadline,
    current_time,
    open_nursery,
    run,
)
from ._core._multierror import MultiError as _MultiError
from ._core._multierror import NonBaseMultiError as _NonBaseMultiError
from ._deprecate import TrioDeprecationWarning
from ._dtls import DTLSChannel, DTLSEndpoint
from ._file_io import open_file, wrap_file
from ._highlevel_generic import StapledStream, aclose_forcefully
from ._highlevel_open_tcp_listeners import open_tcp_listeners, serve_tcp
from ._highlevel_open_tcp_stream import open_tcp_stream
from ._highlevel_open_unix_stream import open_unix_socket
from ._highlevel_serve_listeners import serve_listeners
from ._highlevel_socket import SocketListener, SocketStream
from ._highlevel_ssl_helpers import (
    open_ssl_over_tcp_listeners,
    open_ssl_over_tcp_stream,
    serve_ssl_over_tcp,
)
from ._path import Path
from ._signals import open_signal_receiver
from ._ssl import NeedHandshakeError, SSLListener, SSLStream
from ._subprocess import Process, run_process
from ._sync import CapacityLimiter, Condition, Event, Lock, Semaphore, StrictFIFOLock
from ._timeouts import (
    TooSlowError,
    fail_after,
    fail_at,
    move_on_after,
    move_on_at,
    sleep,
    sleep_forever,
    sleep_until,
)
from ._version import __version__

# Not imported by default, but mentioned here so static analysis tools like
# pylint will know that it exists.
if False:
    from . import testing

from . import _deprecate

_deprecate.enable_attribute_deprecations(__name__)

__deprecated_attributes__ = {
    "open_process": _deprecate.DeprecatedAttribute(
        value=lowlevel.open_process,
        version="0.20.0",
        issue=1104,
        instead="trio.lowlevel.open_process",
    ),
    "MultiError": _deprecate.DeprecatedAttribute(
        value=_MultiError,
        version="0.22.0",
        issue=2211,
        instead=(
            "BaseExceptionGroup (on Python 3.11 and later) or "
            "exceptiongroup.BaseExceptionGroup (earlier versions)"
        ),
    ),
    "NonBaseMultiError": _deprecate.DeprecatedAttribute(
        value=_NonBaseMultiError,
        version="0.22.0",
        issue=2211,
        instead=(
            "ExceptionGroup (on Python 3.11 and later) or "
            "exceptiongroup.ExceptionGroup (earlier versions)"
        ),
    ),
}

# Having the public path in .__module__ attributes is important for:
# - exception names in printed tracebacks
# - sphinx :show-inheritance:
# - deprecation warnings
# - pickle
# - probably other stuff
from ._util import fixup_module_metadata

fixup_module_metadata(__name__, globals())
fixup_module_metadata(lowlevel.__name__, lowlevel.__dict__)
fixup_module_metadata(socket.__name__, socket.__dict__)
fixup_module_metadata(abc.__name__, abc.__dict__)
fixup_module_metadata(from_thread.__name__, from_thread.__dict__)
fixup_module_metadata(to_thread.__name__, to_thread.__dict__)
del fixup_module_metadata
