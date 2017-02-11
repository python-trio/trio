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
# Note that there are various docs out there, including the MSDN
# GenerateConsoleCtrlEvent docs, which claim that the secret to this is to
# create a new process group with CREATE_NEW_PROCESS_GROUP. AFAICT, this
# should work in theory! And it would be much simpler! There is one wrinkle,
# which is that CREATE_NEW_PROCESS_GROUP also inexplicably resets the "should
# we ignore CTRL_C_EVENT" flag, so you have to undo that using
# SetConsoleCtrlHandler(NULL, 0). But once you've done that, it should work!
# And it works in little test cases, like:
#
#   https://github.com/njsmith/appveyor-ctrl-c-test
#
# But... if I try to use it to run the trio test suite, then somehow the
# parent process still gets hit with CTRL_C_EVENT! It's totally inexplicable!
# See:
#
#   https://github.com/njsmith/trio/commit/4d95c42ca937c9336836f7ec29b846e9d655c50f
#   https://ci.appveyor.com/project/njsmith/trio/build/1.0.58/job/cjgqa84ftvrnaste

import sys
import subprocess
import msvcrt

(cmd,) = sys.argv[1:]

process = subprocess.Popen(
    cmd,
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
