# Needs to be defined early so it can be imported:
def _public(fn):
    # Used to mark methods on _Runner and on IOManager implementations that
    # should be wrapped as global context-sensitive functions (see the bottom
    # of _run.py for the wrapper implementation).
    fn._public = True
    return fn


__all__ = []

from ._exceptions import *
__all__ += _exceptions.__all__

from ._multierror import *
__all__ += _multierror.__all__

from ._result import *
__all__ += _result.__all__

from ._traps import *
__all__ += _traps.__all__

from ._ki import *
__all__ += _ki.__all__

from ._run import *
__all__ += _run.__all__

from ._entry_queue import *
__all__ += _entry_queue.__all__

from ._parking_lot import *
__all__ += _parking_lot.__all__

from ._unbounded_queue import *
__all__ += _unbounded_queue.__all__

from ._local import *
__all__ += _local.__all__

from ._subprocess import *
__all__ += _subprocess.__all__

if hasattr(_run, "wait_readable"):
    import socket as _stdlib_socket

    async def wait_socket_readable(sock):
        if type(sock) != _stdlib_socket.socket:
            raise TypeError("need a socket")
        await wait_readable(sock)

    async def wait_socket_writable(sock):
        if type(sock) != _stdlib_socket.socket:
            raise TypeError("need a socket")
        await wait_writable(sock)

    __all__ += ["wait_socket_readable", "wait_socket_writable"]
