import select
import subprocess

from ... import _core


async def test_kqueue_monitor_proc_event():
    p = subprocess.Popen(['sleep', '0.1'])
    ident = p.pid
    filter = select.KQ_FILTER_PROC
    fflags = select.KQ_NOTE_EXIT
    with _core.monitor_kevent(ident, filter, fflags) as q:
        async for batch in q:
            for evt in batch:
                assert evt.ident == ident
                assert evt.filter == filter
                assert evt.fflags == fflags
                assert evt.data == 0  # exit code
                # we only expect one event for KQ_NOTE_EXIT
                return
