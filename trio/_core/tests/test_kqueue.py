import select
import subprocess

import pytest

from ... import _core

use_kqueue = hasattr(select, 'kqueue')
pytestmark = pytest.mark.skipif(not use_kqueue, reason="kqueue platforms only")


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
