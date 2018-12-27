from ._subprocess import Process

# Reexport constants and exceptions from the stdlib subprocess module
from subprocess import (
    PIPE, STDOUT, DEVNULL, CalledProcessError, SubprocessError, TimeoutExpired,
    CompletedProcess
)

# Windows only
try:
    from subprocess import (
        STARTUPINFO, STD_INPUT_HANDLE, STD_OUTPUT_HANDLE, STD_ERROR_HANDLE,
        SW_HIDE, STARTF_USESTDHANDLES, STARTF_USESHOWWINDOW,
        CREATE_NEW_CONSOLE, CREATE_NEW_PROCESS_GROUP
    )
except ImportError:
    pass

# Windows 3.7+ only
try:
    from subprocess import (
        ABOVE_NORMAL_PRIORITY_CLASS, BELOW_NORMAL_PRIORITY_CLASS,
        HIGH_PRIORITY_CLASS, IDLE_PRIORITY_CLASS, NORMAL_PRIORITY_CLASS,
        REALTIME_PRIORITY_CLASS, CREATE_NO_WINDOW, DETACHED_PROCESS,
        CREATE_DEFAULT_ERROR_MODE, CREATE_BREAKAWAY_FROM_JOB
    )
except ImportError:
    pass
