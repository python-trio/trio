# writeable on windows:
# http://stackoverflow.com/a/28848834
# maybe this is usable? (Windows 8+ only though :-()
# https://msdn.microsoft.com/en-us/library/windows/desktop/ms741576(v=vs.85).aspx
# -> can't figure out how to hook events up to iocp :-(
# also of note:
# - to be usable with IOCP, you have to pass a special flag when *creating*
# socket or file objects, and this can affect the semantics of other
# operations on them.
#   - there's ReOpenFile, but it may not work in all cases:
#     https://msdn.microsoft.com/en-us/library/aa365497%28VS.85%29.aspx
#     https://stackoverflow.com/questions/2475713/is-it-possible-to-change-handle-that-has-been-opened-for-synchronous-i-o-to-be-o
#     DuplicateHandle does *not* work for this
#       https://blogs.msdn.microsoft.com/oldnewthing/20140711-00/?p=523
#       https://msdn.microsoft.com/en-us/library/windows/desktop/ms741565(v=vs.85).aspx
#   - stdin/stdout are a bit of a problem in this regard (e.g. IPython) -
#     console handle does not have the special flag set :-(
#   - it is at least possible to detect this, b/c when you try to associate
#     the handle with the IOCP then it will fail. can fall back on threads or
#     whatever at that point.
# - cancellation exists, but you still have to wait for the cancel to finish
# (and there's a race, so it might fail -- the operation might complete
# successfully even though you tried to cancel it)
# this means we can't depend on synchronously cancelling stuff.
# - if a file handle has the special overlapped flag set, then it doesn't have
# a file position, you can *only* do pread/pwrite
# -
# https://msdn.microsoft.com/en-us/library/windows/desktop/ms740087(v=vs.85).aspx
# says that after you cancel a socket operation, the only valid operation is
# to immediately close that socket. this isn't mentioned anywhere else though...



# We *always* need to check for cancellation before issuing an IOCP call
# so: let's have the lowest-level API be one where you do some standard prep
# -- associate object w/ IOCP and fetch OVERLAPPED? -- and that checks for
# cancellation.
