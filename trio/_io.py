import os
import select

if os.name == "nt":
    from ._io_windows import WakeupIOCP as TheWaker
    from ._io_windows import IOCPIOManager as TheIOManager
elif hasattr(select, "epoll"):
    from ._io_unix import WakeupPipe as TheWaker
    from ._io_unix import EpollIOManager as TheIOManager
elif hasattr(select, "kqueue"):
    from ._io_unix import WakeupPipe as TheWaker
    from ._io_unix import KqueueIOManager as TheIOManager
else:
    raise NotImplementedError("unsupported platform")
