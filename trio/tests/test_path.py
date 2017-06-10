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
    async with await path.open('w') as f:
        assert isinstance(f, trio.AsyncIOWrapper)

    assert f.closed


async def test_forwarded_properties(path):
    # use `name` as a representative of forwarded properties

    assert 'name' in dir(path)
    assert path.name == 'test'


async def test_async_method_signature(path):
    # use `resolve` as a representative of wrapped methods

    assert path.resolve.__name__ == 'resolve'
    assert path.resolve.__qualname__ == 'AsyncPath.resolve'

    assert 'pathlib.Path.resolve' in path.resolve.__doc__
