import threading
import time
from io import StringIO

import contextlib

from ..tests.tutil import slow
from .. import _run


@slow
async def test_watchdog():
    watchdog = _run.GLOBAL_RUN_CONTEXT.watchdog
    target = StringIO()
    with contextlib.redirect_stderr(target):
        time.sleep(7)

    assert target.getvalue().startswith(
        "Trio Watchdog has not received any "
        "notifications in 5 seconds, main "
        "thread is blocked!"
    )

    # checkpoint to ensure the watchdog gets a notification, sees that its
    # dead, and winds down its thread
    watchdog.stop()
    await _run.checkpoint()
    time.sleep(6)  # ensure if the watchdog is waiting for 5s, it wakes
    await _run.checkpoint()
    assert not watchdog._thread.is_alive()
