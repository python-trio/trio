# Note: 'cmd' here should be like 'python ...' or python -m pytest ...' etc.
# *Not* 'py ...' or 'pytest ...'
# See https://stackoverflow.com/questions/42180468/on-windows-what-is-the-python-launcher-py-doing-that-lets-control-c-cross-bet

import sys
import subprocess
import signal

(cmd,) = sys.argv[1:]
result = subprocess.run(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
print(result.returncode)
sys.exit(result.returncode)
