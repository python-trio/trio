import time

import contextlib
from io import StringIO

from ..tests.tutil import slow
from ... import _core
from ..._timeouts import sleep

MAGIC_TEXT = "Trio Watchdog has not received any notifications in 5 seconds, \
main thread is blocked!"


@slow
def test_watchdog():
    async def _inner_test():
        target = StringIO()
        with contextlib.redirect_stderr(target):
            time.sleep(2)

        assert target.getvalue().startswith(MAGIC_TEXT)

        target = StringIO()
        with contextlib.redirect_stderr(target):
            await sleep(2)

        # if pytest puts garbage in stderr this won't fail
        assert not target.getvalue().startswith(MAGIC_TEXT)

    _core.run(_inner_test, use_watchdog=True, watchdog_timeout=1)
