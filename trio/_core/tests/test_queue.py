import pytest

from ... import _core

# XX write real tests

async def test_queue_basic():
    q = _core.Queue(_core.Queue.UNLIMITED)
    q.put_nowait("hi")
    assert await q.get_all() == ["hi"]
