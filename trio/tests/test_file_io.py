import io
import tempfile

import pytest
from unittest import mock
from unittest.mock import patch, sentinel

import trio
from trio import _core
from trio._file_io._file_io import _FILE_SYNC_ATTRS, _FILE_ASYNC_METHODS


@pytest.fixture
def path(tmpdir):
    return tmpdir.join('test').__fspath__()


@pytest.fixture
def wrapped():
    return mock.Mock(spec_set=io.StringIO)


@pytest.fixture
def async_file(wrapped):
    return trio.wrap_file(wrapped)


def test_wrap_invalid():
    with pytest.raises(TypeError):
        trio.wrap_file(str())


def test_wrapped_property(async_file, wrapped):
    assert async_file.wrapped == wrapped


def test_sync_attrs_forwarded(async_file, wrapped):
    for attr_name in async_file._available_sync_attrs:
        assert getattr(async_file, attr_name) == getattr(wrapped, attr_name)


def test_sync_attrs_invalid_not_forwarded(async_file):
    async_file._wrapped = sentinel

    assert hasattr(async_file.wrapped, 'invalid_attr')

    with pytest.raises(AttributeError):
        getattr(async_file, 'invalid_attr')


def test_sync_attrs_in_dir():
    inst = trio.AsyncIO(io.StringIO())

    assert all(attr in dir(inst) for attr in inst._available_sync_attrs)


def test_async_methods_generated_once(async_file):
    for meth_name in async_file._available_async_methods:
        assert getattr(async_file, meth_name) == getattr(async_file, meth_name)


def test_async_methods_signature(async_file):
    # use read as a representative of all async methods
    assert async_file.read.__name__ == 'read'
    assert async_file.read.__qualname__ == 'AsyncIO.read'

    assert 'io.StringIO.read' in async_file.read.__doc__


async def test_async_methods_wrap(async_file, wrapped):
    skip = ['detach']

    for meth_name in async_file._available_async_methods:
        if meth_name in skip:
            continue

        meth = getattr(async_file, meth_name)
        wrapped_meth = getattr(wrapped, meth_name)

        value = await meth(sentinel.argument, keyword=sentinel.keyword)

        wrapped_meth.assert_called_once_with(sentinel.argument, keyword=sentinel.keyword)
        assert value == wrapped_meth()

        wrapped.reset_mock()


async def test_open(path):
    f = await trio.open_file(path, 'w')

    assert isinstance(f, trio.AsyncIO)

    await f.close()


async def test_open_context_manager(path):
    async with await trio.open_file(path, 'w') as f:
        assert isinstance(f, trio.AsyncIO)
        assert not f.closed

    assert f.closed


async def test_async_iter(async_file):
    async_file._wrapped = io.StringIO('test\nfoo\nbar')
    expected = iter(list(async_file.wrapped))
    async_file.wrapped.seek(0)

    async for actual in async_file:
        assert actual == next(expected)

    with pytest.raises(StopIteration):
        next(expected)


async def test_close_cancelled(path):
    with _core.open_cancel_scope() as cscope:
        async with await trio.open_file(path, 'w') as f:
            cscope.cancel()
            with pytest.raises(_core.Cancelled):
                await f.write('a')

    assert f.closed


async def test_detach_rewraps_asynciobase():
    raw = io.BytesIO()
    buffered = io.BufferedReader(raw)

    async_file = trio.wrap_file(buffered)

    detached = await async_file.detach()

    assert isinstance(detached, trio.AsyncIO)
    assert detached.wrapped == raw
