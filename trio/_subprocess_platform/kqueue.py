import select
from .. import _core, _subprocess


async def wait_child_exiting(process: "_subprocess.Process") -> None:
    kqueue = _core.current_kqueue()
    try:
        from select import KQ_NOTE_EXIT
    except ImportError:  # pragma: no cover
        # pypy doesn't define KQ_NOTE_EXIT:
        # https://bitbucket.org/pypy/pypy/issues/2921/
        # I verified this value against both Darwin and FreeBSD
        KQ_NOTE_EXIT = 0x80000000

    make_event = lambda flags: select.kevent(
        process.pid,
        filter=select.KQ_FILTER_PROC,
        flags=flags,
        fflags=KQ_NOTE_EXIT
    )

    try:
        kqueue.control(
            [make_event(select.KQ_EV_ADD | select.KQ_EV_ONESHOT)], 0
        )
    except ProcessLookupError:
        # This can happen if the process has already exited.
        # Frustratingly, it does _not_ synchronize with calls
        # to wait() and friends -- it's possible for kevent to
        # return ESRCH but waitpid(..., WNOHANG) still returns
        # nothing. And OS X doesn't support waitid() so we
        # can't fall back to the Linux-style approach. So
        # we'll just suppress the error, and let the caller
        # assume their wait won't block for long.
        return

    def abort(_):
        kqueue.control([make_event(select.KQ_EV_DELETE)], 0)
        return _core.Abort.SUCCEEDED

    await _core.wait_kevent(process.pid, select.KQ_FILTER_PROC, abort)
