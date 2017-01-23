import pytest

from ... import _core

# XX write real tests

async def test_UnboundedQueue_basic():
    q = _core.UnboundedQueue()
    q.put_nowait("hi")
    assert await q.get_all() == ["hi"]
