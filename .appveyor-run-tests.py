# On Appveyor, we run our tests on a new console.
#
# This is needed because our tests send the test process simulated control-C
# events, and on Windows, those go to the entire process group. Without this,
# Appveyor gets confused and after the tests run it says:
#
#    Terminate batch job (Y/N)?
#
# and the it sits waiting for input.
#
# This is a terrific hassle, but I'm not sure what else we can do...

TEST_CMD = "pytest -ra --pyargs trio -v --cov=trio --cov-config=../.coveragerc"

import sys
import subprocess
import msvcrt

process = subprocess.Popen(
    TEST_CMD,
    # This puts the test program into a new console. CTRL_C_EVENT is global to
    # a console, so this is necessary to isolate it from the test running
    # apparatus.
    creationflags=subprocess.CREATE_NEW_CONSOLE,
    # Normally, a new console would get a new window. This hides that window
    # (for some reason).
    shell=True,
    # But we don't want our output to go to a hidden window. Or even a
    # non-hidden window. That would not be helpful. We want it to go to the
    # appveyor log. So we explictly force the output to go to *our*
    # stdout/stderr, i.e., *our* console, not the new console we just
    # created. Except trying to pass stdout=sys.stdout doesn't seem to work
    # for some reason (couldn't figure out why), so we have to explicitly copy
    # data over.
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    )
sys.stdout = sys.stdout.detach()
while True:
    buf = process.stdout.read(1)
    if not buf:
        break
    sys.stdout.write(buf)
    sys.stdout.flush()
process.wait()
sys.stdout.write(b"%i\n" % (process.returncode,))
sys.exit(process.returncode)
