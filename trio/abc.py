# This is a public namespace, so we don't want to expose any non-underscored
# attributes that aren't actually part of our public API. But it's very
# annoying to carefully always use underscored names for module-level
# temporaries, imports, etc. when implementing the module. So we put the
# implementation in an underscored module, and then re-export the public parts
# here.

# Uses `from x import y as y` for compatibility with `pyright --verifytypes` (#2625)
from ._abc import (
    Clock as Clock,
    Instrument as Instrument,
    AsyncResource as AsyncResource,
    SendStream as SendStream,
    ReceiveStream as ReceiveStream,
    Stream as Stream,
    HalfCloseableStream as HalfCloseableStream,
    SocketFactory as SocketFactory,
    HostnameResolver as HostnameResolver,
    Listener as Listener,
    SendChannel as SendChannel,
    ReceiveChannel as ReceiveChannel,
    Channel as Channel,
)
