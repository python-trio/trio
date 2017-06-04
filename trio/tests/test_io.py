import io as _io
import tempfile

import pytest
from unittest import mock
from unittest.mock import patch, sentinel

import trio
from trio import _core


concrete_cls = [
    _io.StringIO, # io.TextIOBase
    _io.BytesIO, # io.BufferedIOBase
    _io.FileIO, # io.RawIOBase
    _io.IOBase #
]

wrapper_cls = [
    trio.AsyncTextIOBase,
    trio.AsyncBufferedIOBase,
    trio.AsyncRawIOBase,
    trio.AsyncIOBase
]


@pytest.fixture
def path(tmpdir):
    return tmpdir.join('test').__fspath__()


@pytest.mark.parametrize("cls,wrap_cls", zip(concrete_cls, wrapper_cls))
def test_wrap(cls, wrap_cls):
    wrapped = trio.wrap_file(cls.__new__(cls))

    assert isinstance(wrapped, wrap_cls)


def test_wrap_invalid():
    with pytest.raises(TypeError):
        trio.wrap_file(str())


@pytest.mark.parametrize("wrap_cls", wrapper_cls)
def test_types_forward(wrap_cls):
    inst = wrap_cls(sentinel)

    for attr_name in wrap_cls._forward:
        assert getattr(inst, attr_name) == getattr(sentinel, attr_name)


def test_types_forward_invalid():
    inst = trio.AsyncIOBase(None)

    with pytest.raises(AttributeError):
        inst.nonexistant_attr


def test_types_forward_in_dir():
    inst = trio.AsyncIOBase(None)

    assert all(attr in dir(inst) for attr in inst._forward)


@pytest.mark.parametrize("cls,wrap_cls", zip(concrete_cls, wrapper_cls))
async def test_types_wrap(cls, wrap_cls):
    mock_cls = mock.Mock(spec_set=cls)
    inst = wrap_cls(mock_cls)

    for meth_name in wrap_cls._wrap + trio.AsyncIOBase._wrap:
        meth = getattr(inst, meth_name)
        mock_meth = getattr(mock_cls, meth_name)

        value = await meth(sentinel.argument, kw=sentinel.kw)

        mock_meth.assert_called_once_with(sentinel.argument, kw=sentinel.kw)
        assert value == mock_meth()
        mock_cls.reset_mock()


async def test_open_context_manager(path):
    async with trio.open_file(path, 'w') as f:
        assert isinstance(f, trio.AsyncIOBase)
        assert not f.closed

    assert f.closed


async def test_open_await(path):
    f = await trio.open_file(path, 'w')

    assert isinstance(f, trio.AsyncIOBase)
    assert not f.closed

    await f.close()


async def test_open_await_context_manager(path):
    f = await trio.open_file(path, 'w')
    async with f:
        assert not f.closed

    assert f.closed


async def test_async_iter():
    string = 'test\nstring\nend'

    inst = trio.wrap_file(_io.StringIO(string))

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
