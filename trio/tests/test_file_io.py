import io
import tempfile

import pytest
from unittest import mock
from unittest.mock import patch, sentinel

import trio
from trio import _core


concrete_cls = [
    io.StringIO,
    io.BytesIO,
    io.FileIO,
    io.IOBase
]


@pytest.fixture
def path(tmpdir):
    return tmpdir.join('test').__fspath__()


def test_wrap_invalid():
    with pytest.raises(TypeError):
        trio.wrap_file(str())


def test_types_forward():
    inst = trio.AsyncIO(sentinel)

    for attr_name in inst._available_sync_attrs:
        assert getattr(inst, attr_name) == getattr(sentinel, attr_name)


def test_types_forward_invalid():
    inst = trio.AsyncIO(None)

    with pytest.raises(AttributeError):
        inst.nonexistant_attr


def test_types_forward_in_dir():
    inst = trio.AsyncIO(io.StringIO())

    assert all(attr in dir(inst) for attr in inst._available_sync_attrs)


@pytest.mark.parametrize("cls", zip(concrete_cls))
async def test_types_wrap(cls):
    mock_cls = mock.Mock(spec_set=cls)
    inst = trio.AsyncIO(mock_cls)

    for meth_name in inst._available_async_methods:
        meth = getattr(inst, meth_name)
        mock_meth = getattr(mock_cls, meth_name)

        value = await meth(sentinel.argument, kw=sentinel.kw)

        mock_meth.assert_called_once_with(sentinel.argument, kw=sentinel.kw)
        assert value == mock_meth()
        mock_cls.reset_mock()


async def test_open_context_manager(path):
    async with trio.open_file(path, 'w') as f:
        assert isinstance(f, trio.AsyncIO)
        assert not f.closed

    assert f.closed


async def test_open_await(path):
    f = await trio.open_file(path, 'w')

    assert isinstance(f, trio.AsyncIO)
    assert not f.closed

    await f.close()


async def test_open_await_context_manager(path):
    f = await trio.open_file(path, 'w')
    async with f:
        assert not f.closed

    assert f.closed


async def test_async_iter():
    string = 'test\nstring\nend'

    inst = trio.wrap_file(io.StringIO(string))

    expected = iter(string.splitlines(True))
    async for actual in inst:
        assert actual == next(expected)


async def test_close_cancelled(path):
    with _core.open_cancel_scope() as cscope:
        async with trio.open_file(path, 'w') as f:
            cscope.cancel()
            with pytest.raises(_core.Cancelled):
                await f.write('a')

    assert f.closed


async def test_detach_rewraps_asynciobase():
    raw = io.BytesIO()
    buffered = io.BufferedReader(raw)

    inst = trio.AsyncIO(buffered)

    detached = await inst.detach()

    assert isinstance(detached, trio.AsyncIO)
    assert detached._wrapped == raw


async def test_async_method_generated_once():
    inst = trio.wrap_file(io.StringIO())

    for meth_name in inst._available_async_methods:
        assert getattr(inst, meth_name) == getattr(inst, meth_name)


async def test_wrapped_property():
    wrapped = io.StringIO()
    inst = trio.wrap_file(wrapped)

    assert inst.wrapped == wrapped


async def test_async_method_signature():
    inst = trio.wrap_file(io.StringIO())

    # use read as a representative of all async methods
    assert inst.read.__name__ == 'read'
    assert inst.read.__qualname__ == 'AsyncIO.read'

    assert 'io.StringIO.read' in inst.read.__doc__
