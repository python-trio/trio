# subprocesses are a huge hassle
# on Linux there is simply no way to async wait for a child to exit except by
# messing with SIGCHLD and that is ... *such* a mess. Not really
# tenable. We're better off trying os.waitpid(..., os.WNOHANG), and if that
# says the process is still going then spawn a thread to sit in waitpid.

# on Mac/*BSD then kqueue works, go them.

# on Windows, you can either do the thread thing, or something involving
# WaitForMultipleObjects, or the Job Object API:
# https://stackoverflow.com/questions/17724859/detecting-exit-failure-of-child-processes-using-iocp-c-windows
# (see also the comments here about using the Job Object API:
# https://stackoverflow.com/questions/23434842/python-how-to-kill-child-processes-when-parent-dies/23587108#23587108)

# We'll probably want to mess with the job API anyway for worker processes
# (b/c that's the reliable way to make sure we never leave residual worker
# processes around after exiting, see that stackoverflow question again), so
# maybe this isn't too big a hassle? waitpid is probably easiest for the
# first-pass implementation though.
