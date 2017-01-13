import os
import select

if os.name == "nt":
    from ._io_windows import WakeupIOCP as THE_WAKER
    from ._io_windows import IOCPIOManager as THE_IO_MANAGER
elif hasattr(select, "epoll"):
    from ._io_unix import WakeupPipe as THE_WAKER
    from ._io_unix import EpollIOManager as THE_IO_MANAGER
elif hasattr(select, "kqueue"):
    from ._io_unix import WakeupPipe as THE_WAKER
    from ._io_unix import KqueueIOManager as THE_IO_MANAGER
else:
    raise NotImplementedError("unsupported platform")
