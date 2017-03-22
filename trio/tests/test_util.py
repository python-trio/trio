import pytest

import signal

from .. import _util

async def test_signal_raise():
    record = []
    def handler(signum, _):
        record.append(signum)

    old = signal.signal(signal.SIGFPE, handler)
    try:
        _util.signal_raise(signal.SIGFPE)
    finally:
        signal.signal(signal.SIGFPE, old)
    assert record == [signal.SIGFPE]
