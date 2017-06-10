import pathlib

import pytest

import trio


@pytest.fixture
def path(tmpdir):
    p = tmpdir.join('test').__fspath__()
    return trio.AsyncPath(p)


def method_pair(path, method_name):
    path = pathlib.Path(path)
    async_path = trio.AsyncPath(path)
    return getattr(path, method_name), getattr(async_path, method_name)


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


@pytest.mark.parametrize('method_name', ['is_dir', 'is_file'])
async def test_compare_async_stat_methods(method_name):

    method, async_method = method_pair('.', method_name)

    result = method()
    async_result = await async_method()

    assert result == async_result


async def test_invalid_name_not_wrapped(path):
    with pytest.raises(AttributeError):
        getattr(path, 'invalid_fake_attr')


@pytest.mark.parametrize('method_name', ['absolute', 'resolve'])
async def test_forward_functions_rewrap(method_name):

    method, async_method = method_pair('.', method_name)

    result = method()
    async_result = await async_method()

    assert isinstance(async_result, trio.AsyncPath)
    assert result.__fspath__() == async_result.__fspath__()
