import pathlib

import pytest

import trio


@pytest.fixture
def path():
    return trio.AsyncPath()


async def test_windows_owner_group_raises(path):
    path._wrapped.__class__ = pathlib.WindowsPath

    assert isinstance(path._wrapped, pathlib.WindowsPath)

    with pytest.raises(NotImplementedError):
        await path.owner()

    with pytest.raises(NotImplementedError):
        await path.group()
