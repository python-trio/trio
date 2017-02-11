import sys
import subprocess
import signal

# Even though we run the child in a new process group, I was somehow getting
# KeyboardInterrupts raised *here*. This makes absolutely no sense to me. I
# couldn't reproduce it when running a minimal program that just raises
# CTRL_C_EVENT.
signal.signal(signal.SIGINT, signal.SIG_IGN)

(cmd,) = sys.argv[1:]
result = subprocess.run(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
print(result.returncode)
sys.exit(result.returncode)
