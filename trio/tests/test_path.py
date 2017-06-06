import pathlib

import pytest

import trio


@pytest.fixture
def path(tmpdir):
    p = tmpdir.join('test').__fspath__()
    return trio.AsyncPath(p)


async def test_windows_owner_group_raises(path):
    path._wrapped.__class__ = pathlib.WindowsPath

    assert isinstance(path._wrapped, pathlib.WindowsPath)

    with pytest.raises(NotImplementedError):
        await path.owner()

    with pytest.raises(NotImplementedError):
        await path.group()


async def test_open_is_async_context_manager(path):
    async with path.open('w') as f:
        assert isinstance(f, trio.AsyncIO)

    assert f.closed


async def test_open_is_awaitable_context_manager(path):
    async with await path.open('w') as f:
        assert isinstance(f, trio.AsyncIO)

    assert f.closed
