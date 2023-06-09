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
#
# Uses `from x import y as y` for compatibility with `pyright --verifytypes` (#2625)

# pyright explicitly does not care about `__version__`
# see https://github.com/microsoft/pyright/blob/main/docs/typed-libraries.md#type-completeness
from ._version import __version__

from ._core import (
    TrioInternalError as TrioInternalError,
    RunFinishedError as RunFinishedError,
    WouldBlock as WouldBlock,
    Cancelled as Cancelled,
    BusyResourceError as BusyResourceError,
    ClosedResourceError as ClosedResourceError,
    run as run,
    open_nursery as open_nursery,
    CancelScope as CancelScope,
    current_effective_deadline as current_effective_deadline,
    TASK_STATUS_IGNORED as TASK_STATUS_IGNORED,
    current_time as current_time,
    BrokenResourceError as BrokenResourceError,
    EndOfChannel as EndOfChannel,
    Nursery as Nursery,
)

from ._timeouts import (
    move_on_at as move_on_at,
    move_on_after as move_on_after,
    sleep_forever as sleep_forever,
    sleep_until as sleep_until,
    sleep as sleep,
    fail_at as fail_at,
    fail_after as fail_after,
    TooSlowError as TooSlowError,
)

from ._sync import (
    Event as Event,
    CapacityLimiter as CapacityLimiter,
    Semaphore as Semaphore,
    Lock as Lock,
    StrictFIFOLock as StrictFIFOLock,
    Condition as Condition,
)

from ._highlevel_generic import (
    aclose_forcefully as aclose_forcefully,
    StapledStream as StapledStream,
)

from ._channel import (
    open_memory_channel as open_memory_channel,
    MemorySendChannel as MemorySendChannel,
    MemoryReceiveChannel as MemoryReceiveChannel,
)

from ._signals import open_signal_receiver as open_signal_receiver

from ._highlevel_socket import (
    SocketStream as SocketStream,
    SocketListener as SocketListener,
)

from ._file_io import open_file as open_file, wrap_file as wrap_file

from ._path import Path as Path

from ._subprocess import Process as Process, run_process as run_process

from ._ssl import (
    SSLStream as SSLStream,
    SSLListener as SSLListener,
    NeedHandshakeError as NeedHandshakeError,
)

from ._dtls import DTLSEndpoint as DTLSEndpoint, DTLSChannel as DTLSChannel

from ._highlevel_serve_listeners import serve_listeners as serve_listeners

from ._highlevel_open_tcp_stream import open_tcp_stream as open_tcp_stream

from ._highlevel_open_tcp_listeners import (
    open_tcp_listeners as open_tcp_listeners,
    serve_tcp as serve_tcp,
)

from ._highlevel_open_unix_stream import open_unix_socket as open_unix_socket

from ._highlevel_ssl_helpers import (
    open_ssl_over_tcp_stream as open_ssl_over_tcp_stream,
    open_ssl_over_tcp_listeners as open_ssl_over_tcp_listeners,
    serve_ssl_over_tcp as serve_ssl_over_tcp,
)

from ._core._multierror import MultiError as _MultiError
from ._core._multierror import NonBaseMultiError as _NonBaseMultiError

from ._deprecate import TrioDeprecationWarning as TrioDeprecationWarning

# Submodules imported by default
from . import lowlevel
from . import socket
from . import abc
from . import from_thread
from . import to_thread

# Not imported by default, but mentioned here so static analysis tools like
# pylint will know that it exists.
if False:
    from . import testing

from . import _deprecate as _deprecate

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
