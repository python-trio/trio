# subprocesses are a huge hassle
# on Linux there is simply no way to async wait for a child to exit except by
# messing with SIGCHLD and that is ... *such* a mess. Not really
# tenable. We're better off trying os.waitpid(..., os.WNOHANG), and if that
# says the process is still going then spawn a thread to sit in waitpid.
# ......though that waitpid is non-cancellable so ugh. this is a problem,
# becaues it's also mutating -- you only get to waitpid() once, and you have
# to do it, because zombies. I guess we could make sure the waitpid thread is
# daemonic and either it gets back to us eventually (even if our first call to
# 'await wait()' is cancelled, maybe another one won't be), or else we go away
# and don't care anymore.
# I guess simplest is just to spawn a thread at the same time as we spawn the
# process, with more reasonable notification semantics.
# or we can poll every 100 ms or something, sigh.

# on Mac/*BSD then kqueue works, go them. (maybe have WNOHANG after turning it
# on to avoid a race condition I guess)

# on Windows, you can either do the thread thing, or something involving
# WaitForMultipleObjects, or the Job Object API:
# https://stackoverflow.com/questions/17724859/detecting-exit-failure-of-child-processes-using-iocp-c-windows
# (see also the comments here about using the Job Object API:
# https://stackoverflow.com/questions/23434842/python-how-to-kill-child-processes-when-parent-dies/23587108#23587108)
# however the docs say:
# "Note that, with the exception of limits set with the
# JobObjectNotificationLimitInformation information class, delivery of
# messages to the completion port is not guaranteed; failure of a message to
# arrive does not necessarily mean that the event did not occur"
#
# oh windows wtf

# We'll probably want to mess with the job API anyway for worker processes
# (b/c that's the reliable way to make sure we never leave residual worker
# processes around after exiting, see that stackoverflow question again), so
# maybe this isn't too big a hassle? waitpid is probably easiest for the
# first-pass implementation though.

# the handle version has the same issues as waitpid on Linux, except I guess
# that on windows the waitpid equivalent doesn't consume the handle.
# -- wait no, the windows equivalent takes a timeout! and we know our
# cancellation deadline going in, so that's actually okay. (Still need to use
# a thread but whatever.)

# asyncio does RegisterWaitForSingleObject with a callback that does
# PostQueuedCompletionStatus.
# this is just a thread pool in disguise (and in principle could have weird
# problems if you have enough children and run out of threads)
# it's possible we could do something with a thread that just sits in
# an alertable state and handle callbacks...? though hmm, maybe the set of
# events that can notify via callbacks is equivalent to the set that can
# notify via IOCP.
# there's WaitForMultipleObjects to let multiple waits share a thread I
# guess.
# you can wake up a WaitForMultipleObjectsEx on-demand by using QueueUserAPC
# to send a no-op APC to its thread.
# this is also a way to cancel a WaitForSingleObjectEx, actually. So it
# actually is possible to cancel the equivalent of a waitpid on Windows.


# Potentially useful observation: you *can* use a socket as the
# stdin/stdout/stderr for a child, iff you create that socket *without*
# WSA_FLAG_OVERLAPPED:
#   http://stackoverflow.com/a/5725609
# Here's ncm's Windows implementation of socketpair, which has a flag to
# control whether one of the sockets has WSA_FLAG_OVERLAPPED set:
#   https://github.com/ncm/selectable-socketpair/blob/master/socketpair.c
# (it also uses listen(1) so it's robust against someone intercepting things,
# unlike the version in socket.py... not sure anyone really cares, but
# hey. OTOH it only supports AF_INET, while socket.py supports AF_INET6,
# fancy.)
# (or it would be trivial to (re)implement in python, using either
# socket.socketpair or ncm's version as a model, given a cffi function to
# create the non-overlapped socket in the first place then just pass it into
# the socket.socket constructor (avoiding the dup() that fromfd does).)
