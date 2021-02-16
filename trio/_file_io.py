from functools import partial
import io
import os
from typing import (
    Any,
    # AnyStr,
    # AsyncContextManager,
    AsyncIterator,
    # Awaitable,
    Callable,
    # ContextManager,
    # FrozenSet,
    # Iterator,
    # Mapping,
    # NoReturn,
    Optional,
    Sequence,
    Union,
    # Sequence,
    TypeVar,
    Tuple,
    List,
    Iterable,
    TextIO,
    BinaryIO,
    IO,
    overload,
)

from .abc import AsyncResource
from ._util import async_wraps

import trio

_TSelf = TypeVar("_TSelf")

# This list is also in the docs, make sure to keep them in sync
_FILE_SYNC_ATTRS = {
    "closed",
    "encoding",
    "errors",
    "fileno",
    "isatty",
    "newlines",
    "readable",
    "seekable",
    "writable",
    # not defined in *IOBase:
    "buffer",
    "raw",
    "line_buffering",
    "closefd",
    "name",
    "mode",
    "getvalue",
    "getbuffer",
}

# This list is also in the docs, make sure to keep them in sync
_FILE_ASYNC_METHODS = {
    "flush",
    "read",
    "read1",
    "readall",
    "readinto",
    "readline",
    "readlines",
    "seek",
    "tell",
    "truncate",
    "write",
    "writelines",
    # not defined in *IOBase:
    "readinto1",
    "peek",
}


class AsyncIOWrapper(AsyncResource):
    """A generic :class:`~io.IOBase` wrapper that implements the :term:`asynchronous
    file object` interface. Wrapped methods that could block are executed in
    :meth:`trio.to_thread.run_sync`.

    All properties and methods defined in in :mod:`~io` are exposed by this
    wrapper, if they exist in the wrapped file object.

    """

    def __init__(self, file: io.IOBase) -> None:
        self._wrapped = file

    @property
    def wrapped(self) -> io.IOBase:
        """object: A reference to the wrapped file object"""

        return self._wrapped

    def __getattr__(self, name: str) -> object:
        if name in _FILE_SYNC_ATTRS:
            return getattr(self._wrapped, name)
        if name in _FILE_ASYNC_METHODS:
            meth = getattr(self._wrapped, name)

            @async_wraps(self.__class__, self._wrapped.__class__, name)
            async def wrapper(*args, **kwargs):  # type: ignore[misc, no-untyped-def]
                func = partial(meth, *args, **kwargs)
                return await trio.to_thread.run_sync(func)

            # cache the generated method
            setattr(self, name, wrapper)
            return wrapper

        raise AttributeError(name)

    def __dir__(self) -> Sequence[str]:
        attrs = set(super().__dir__())
        attrs.update(a for a in _FILE_SYNC_ATTRS if hasattr(self.wrapped, a))
        attrs.update(a for a in _FILE_ASYNC_METHODS if hasattr(self.wrapped, a))
        return attrs  # type: ignore[return-value]

    def __aiter__(self: _TSelf) -> _TSelf:
        return self

    async def __anext__(self) -> str:
        line: str = await self.readline()  # type: ignore[operator]
        if line:
            return line
        else:
            raise StopAsyncIteration

    async def detach(self) -> "_AsyncIOBase":
        """Like :meth:`io.BufferedIOBase.detach`, but async.

        This also re-wraps the result in a new :term:`asynchronous file object`
        wrapper.

        """

        raw: Union[io.RawIOBase, BinaryIO] = await trio.to_thread.run_sync(self._wrapped.detach)  # type: ignore[attr-defined]
        return wrap_file(raw)

    async def aclose(self) -> None:
        """Like :meth:`io.IOBase.close`, but async.

        This is also shielded from cancellation; if a cancellation scope is
        cancelled, the wrapped file object will still be safely closed.

        """

        # ensure the underling file is closed during cancellation
        with trio.CancelScope(shield=True):
            await trio.to_thread.run_sync(self._wrapped.close)

        await trio.lowlevel.checkpoint_if_cancelled()


# _file_io
class _AsyncIOBase(trio.abc.AsyncResource):
    closed: bool

    def __aiter__(self) -> AsyncIterator[bytes]:
        ...

    async def __anext__(self) -> bytes:
        ...

    async def aclose(self) -> None:
        ...

    def fileno(self) -> int:
        ...

    async def flush(self) -> None:
        ...

    def isatty(self) -> bool:
        ...

    def readable(self) -> bool:
        ...

    async def readlines(self, hint: int = ...) -> List[bytes]:
        ...

    async def seek(self, offset: int, whence: int = ...) -> int:
        ...

    def seekable(self) -> bool:
        ...

    async def tell(self) -> int:
        ...

    async def truncate(self, size: Optional[int] = ...) -> int:
        ...

    def writable(self) -> bool:
        ...

    async def writelines(self, lines: Iterable[bytes]) -> None:
        ...

    async def readline(self, size: int = ...) -> bytes:
        ...


class _AsyncRawIOBase(_AsyncIOBase):
    async def readall(self) -> bytes:
        ...

    async def readinto(self, b: bytearray) -> Optional[int]:
        ...

    async def write(self, b: bytes) -> Optional[int]:
        ...

    async def read(self, size: int = ...) -> Optional[bytes]:
        ...


class _AsyncBufferedIOBase(_AsyncIOBase):
    async def detach(self) -> _AsyncRawIOBase:
        ...

    async def readinto(self, b: bytearray) -> int:
        ...

    async def write(self, b: bytes) -> int:
        ...

    async def readinto1(self, b: bytearray) -> int:
        ...

    async def read(self, size: Optional[int] = ...) -> bytes:
        ...

    async def read1(self, size: int = ...) -> bytes:
        ...


class _AsyncTextIOBase(_AsyncIOBase):
    encoding: str
    errors: Optional[str]
    newlines: Union[str, Tuple[str, ...], None]

    def __aiter__(self) -> AsyncIterator[str]:  # type: ignore
        ...

    async def __anext__(self) -> str:  # type: ignore
        ...

    async def detach(self) -> _AsyncRawIOBase:
        ...

    async def write(self, s: str) -> int:
        ...

    async def readline(self, size: int = ...) -> str:  # type: ignore
        ...

    async def read(self, size: Optional[int] = ...) -> str:
        ...

    async def seek(self, offset: int, whence: int = ...) -> int:
        ...

    async def tell(self) -> int:
        ...


async def open_file(
    file: Union[os.PathLike, int],
    mode: str = "r",
    buffering: int = -1,
    encoding: Optional[str] = None,
    errors: Optional[str] = None,
    newline: Optional[str] = None,
    closefd: bool = True,
    opener: Optional[Callable[[str, int], int]] = None,
):
    """Asynchronous version of :func:`io.open`.

    Returns:
        An :term:`asynchronous file object`

    Example::

        async with await trio.open_file(filename) as f:
            async for line in f:
                pass

        assert f.closed

    See also:
      :func:`trio.Path.open`

    """
    _file = wrap_file(
        await trio.to_thread.run_sync(
            io.open, file, mode, buffering, encoding, errors, newline, closefd, opener
        )
    )
    return _file


@overload
def wrap_file(obj: Union[TextIO, io.TextIOBase]) -> _AsyncTextIOBase:
    ...


@overload
def wrap_file(obj: Union[BinaryIO, io.BufferedIOBase]) -> _AsyncBufferedIOBase:
    ...


@overload
def wrap_file(obj: io.RawIOBase) -> _AsyncRawIOBase:
    ...


@overload
def wrap_file(obj: Union[IO[Any], io.IOBase]) -> _AsyncIOBase:
    ...


# def wrap_file(obj: Union[IO[Any], io.IOBase, io.RawIOBase, BinaryIO, io.BufferedIOBase, TextIO, io.TextIOBase]) -> _AsyncIOBase:
def wrap_file(file):
    """This wraps any file object in a wrapper that provides an asynchronous
    file object interface.

    Args:
        file: a :term:`file object`

    Returns:
        An :term:`asynchronous file object` that wraps ``file``

    Example::

        async_file = trio.wrap_file(StringIO('asdf'))

        assert await async_file.read() == 'asdf'

    """

    def has(attr: str) -> bool:
        return hasattr(file, attr) and callable(getattr(file, attr))

    if not (has("close") and (has("read") or has("write"))):
        raise TypeError(
            "{} does not implement required duck-file methods: "
            "close and (read or write)".format(file)
        )

    return AsyncIOWrapper(file)
