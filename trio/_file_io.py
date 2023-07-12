from __future__ import annotations

import io
from functools import partial
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    AnyStr,
    BinaryIO,
    Callable,
    Generic,
    Iterable,
    TypeVar,
    Union,
    overload,
)

import trio

from ._util import async_wraps
from .abc import AsyncResource

if TYPE_CHECKING:
    from _typeshed import (
        OpenBinaryMode,
        OpenBinaryModeReading,
        OpenBinaryModeUpdating,
        OpenBinaryModeWriting,
        OpenTextMode,
        StrOrBytesPath,
    )
    from typing_extensions import Literal

# This list is also in the docs, make sure to keep them in sync
_FILE_SYNC_ATTRS: set[str] = {
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
_FILE_ASYNC_METHODS: set[str] = {
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


FileT = TypeVar('FileT')
FileT_co = TypeVar('FileT_co', covariant=True)
T = TypeVar('T')
T_co = TypeVar('T_co', covariant=True)
T_contra = TypeVar('T_contra', contravariant=True)
AnyStr_co = TypeVar('AnyStr_co', str, bytes, covariant=True)
AnyStr_contra = TypeVar('AnyStr_contra', str, bytes, contravariant=True)

# Define a protocol for every method/property we expose. Each is effectively a predicate checking
# whether a class defines this method/property.
if TYPE_CHECKING:
    from typing_extensions import Buffer, Protocol

    class _HasClosed(Protocol):
        @property
        def closed(self) -> bool: ...

    class _HasEncoding(Protocol):
        @property
        def encoding(self) -> str: ...

    class _HasErrors(Protocol):
        @property
        def errors(self) -> str | None: ...

    class _HasFileNo(Protocol):
        def fileno(self) -> int: ...

    class _HasIsATTY(Protocol):
        def isatty(self) -> bool: ...

    class _HasNewlines(Protocol):
        @property
        def newlines(self) -> Any: ...  # None, str or tuple

    class _HasReadable(Protocol):
        def readable(self) -> bool: ...

    class _HasSeekable(Protocol):
        def seekable(self) -> bool: ...

    class _HasWritable(Protocol):
        def writable(self) -> bool: ...

    class _HasBuffer(Protocol):
        @property
        def buffer(self) -> BinaryIO: ...

    class _HasRaw(Protocol):
        @property
        def raw(self) -> io.RawIOBase: ...

    class _HasLineBuffering(Protocol):
        @property
        def line_buffering(self) -> bool: ...

    class _HasCloseFD(Protocol):
        @property
        def closefd(self) -> bool: ...

    class _HasName(Protocol):
        @property
        def name(self) -> str: ...

    class _HasMode(Protocol):
        @property
        def mode(self) -> str: ...

    class _CanGetValue(Protocol[AnyStr_co]):
        def getvalue(self) -> AnyStr_co: ...

    class _CanGetBuffer(Protocol):
        def getbuffer(self) -> memoryview: ...

    class _CanFlush(Protocol):
        def flush(self) -> None: ...

    class _CanRead(Protocol[AnyStr_co]):
        def read(self, __size: int | None = ...) -> AnyStr_co: ...

    class _CanRead1(Protocol):
        def read1(self, __size: int | None = ...) -> bytes: ...

    class _CanReadAll(Protocol[AnyStr_co]):
        def readall(self) -> AnyStr_co: ...

    class _CanReadInto(Protocol):
        def readinto(self, __buf: Buffer) -> int | None: ...

    class _CanReadInto1(Protocol):
        def readinto1(self, __buffer: Buffer) -> int: ...

    class _CanReadLine(Protocol[AnyStr_co]):
        def readline(self, __size: int = ...) -> AnyStr_co: ...

    class _CanReadLines(Protocol[AnyStr]):
        def readlines(self, __hint: int = ...) -> list[AnyStr]: ...

    class _CanSeek(Protocol):
        def seek(self, __target: int, __whence: int = 0) -> int: ...

    class _CanTell(Protocol):
        def tell(self) -> int: ...

    class _CanTruncate(Protocol):
        def truncate(self, __size: int | None = ...) -> int: ...

    class _CanWrite(Protocol[AnyStr_contra]):
        def write(self, __data: AnyStr_contra) -> int: ...

    class _CanWriteLines(Protocol[T_contra]):
        def writelines(self, __lines: Iterable[T_contra]) -> None: ...

    class _CanPeek(Protocol[AnyStr_co]):
        def peek(self, __size: int = 0) -> AnyStr_co: ...

    class _CanDetach(Protocol[T_co]):
        def detach(self) -> T_co: ...

    class _CanClose(Protocol):
        def close(self) -> None: ...


class AsyncIOWrapper(AsyncResource, Generic[FileT_co]):
    """A generic :class:`~io.IOBase` wrapper that implements the :term:`asynchronous
    file object` interface. Wrapped methods that could block are executed in
    :meth:`trio.to_thread.run_sync`.

    All properties and methods defined in in :mod:`~io` are exposed by this
    wrapper, if they exist in the wrapped file object.

    """

    def __init__(self, file: FileT_co) -> None:
        self._wrapped = file

    @property
    def wrapped(self) -> FileT_co:
        """object: A reference to the wrapped file object"""

        return self._wrapped

    if not TYPE_CHECKING:
        def __getattr__(self, name: str) -> object:
            if name in _FILE_SYNC_ATTRS:
                return getattr(self._wrapped, name)
            if name in _FILE_ASYNC_METHODS:
                meth = getattr(self._wrapped, name)

                @async_wraps(self.__class__, self._wrapped.__class__, name)
                async def wrapper(*args, **kwargs):
                    func = partial(meth, *args, **kwargs)
                    return await trio.to_thread.run_sync(func)

                # cache the generated method
                setattr(self, name, wrapper)
                return wrapper

            raise AttributeError(name)

    def __dir__(self) -> Iterable[str]:
        attrs = set(super().__dir__())
        attrs.update(a for a in _FILE_SYNC_ATTRS if hasattr(self.wrapped, a))
        attrs.update(a for a in _FILE_ASYNC_METHODS if hasattr(self.wrapped, a))
        return attrs

    def __aiter__(self) -> AsyncIOWrapper[FileT_co]:
        return self

    async def __anext__(self: AsyncIOWrapper[_CanReadLine[AnyStr]]) -> AnyStr:
        line = await self.readline()
        if line:
            return line
        else:
            raise StopAsyncIteration

    async def detach(self: AsyncIOWrapper[_CanDetach[T]]) -> AsyncIOWrapper[T]:
        """Like :meth:`io.BufferedIOBase.detach`, but async.

        This also re-wraps the result in a new :term:`asynchronous file object`
        wrapper.

        """

        raw = await trio.to_thread.run_sync(self._wrapped.detach)
        return wrap_file(raw)

    async def aclose(self: AsyncIOWrapper[_CanClose]) -> None:
        """Like :meth:`io.IOBase.close`, but async.

        This is also shielded from cancellation; if a cancellation scope is
        cancelled, the wrapped file object will still be safely closed.

        """

        # ensure the underling file is closed during cancellation
        with trio.CancelScope(shield=True):
            await trio.to_thread.run_sync(self._wrapped.close)

        await trio.lowlevel.checkpoint_if_cancelled()

    if TYPE_CHECKING:
        # Based on typing.IO and io stubs.
        # For every method/property we type self, restricting these to only be available if
        # the original also is.
        @property
        def closed(self: AsyncIOWrapper[_HasClosed]) -> bool: ...
        @property
        def encoding(self: AsyncIOWrapper[_HasEncoding]) -> str: ...
        @property
        def errors(self: AsyncIOWrapper[_HasErrors]) -> str | None: ...
        @property
        def newlines(self: AsyncIOWrapper[_HasNewlines]) -> Any: ...  # None, str or tuple
        @property
        def buffer(self: AsyncIOWrapper[_HasBuffer]) -> BinaryIO: ...
        @property
        def raw(self: AsyncIOWrapper[_HasRaw]) -> io.RawIOBase: ...
        @property
        def line_buffering(self: AsyncIOWrapper[_HasLineBuffering]) -> int: ...
        @property
        def closefd(self: AsyncIOWrapper[_HasCloseFD]) -> bool: ...
        @property
        def name(self: AsyncIOWrapper[_HasName]) -> str: ...
        @property
        def mode(self: AsyncIOWrapper[_HasMode]) -> str: ...

        def fileno(self: AsyncIOWrapper[_HasFileNo]) -> int: ...
        def isatty(self: AsyncIOWrapper[_HasIsATTY]) -> bool: ...
        def readable(self: AsyncIOWrapper[_HasReadable]) -> bool: ...
        def seekable(self: AsyncIOWrapper[_HasSeekable]) -> bool: ...
        def writable(self: AsyncIOWrapper[_HasWritable]) -> bool: ...
        def getvalue(self: AsyncIOWrapper[_CanGetValue[AnyStr]]) -> AnyStr: ...
        def getbuffer(self: AsyncIOWrapper[_CanGetBuffer]) -> memoryview: ...
        async def flush(self: AsyncIOWrapper[_CanFlush]) -> None: ...
        async def read(self: AsyncIOWrapper[_CanRead[AnyStr]], __size: int | None = ...) -> AnyStr: ...
        async def read1(self: AsyncIOWrapper[_CanRead1], __size: int | None = ...) -> bytes: ...
        async def readall(self: AsyncIOWrapper[_CanReadAll[AnyStr]]) -> AnyStr: ...
        async def readinto(self: AsyncIOWrapper[_CanReadInto], __buf: Buffer) -> int | None: ...
        async def readline(self: AsyncIOWrapper[_CanReadLine[AnyStr]], __size: int = ...) -> AnyStr: ...
        async def readlines(self: AsyncIOWrapper[_CanReadLines[AnyStr]]) -> list[AnyStr]: ...
        async def seek(self: AsyncIOWrapper[_CanSeek], __target: int, __whence: int = 0) -> int: ...
        async def tell(self: AsyncIOWrapper[_CanTell]) -> int: ...
        async def truncate(self: AsyncIOWrapper[_CanTruncate], __size: int | None = ...) -> int: ...
        async def write(self: AsyncIOWrapper[_CanWrite[AnyStr]], __data: AnyStr) -> int: ...
        async def writelines(self: AsyncIOWrapper[_CanWriteLines[T]], __lines: Iterable[T]) -> None: ...
        async def readinto1(self: AsyncIOWrapper[_CanReadInto1], __buffer: Buffer) -> int: ...
        async def peek(self: AsyncIOWrapper[_CanPeek[AnyStr]], __size: int = 0) -> AnyStr: ...


# Type hints are copied from builtin open.
_OpenFile = Union[StrOrBytesPath, int]
_Opener = Callable[[str, int], int]


@overload
async def open_file(
    file: _OpenFile,
    mode: OpenTextMode = ...,
    buffering: int = ...,
    encoding: str | None = ...,
    errors: str | None = ...,
    newline: str | None = ...,
    closefd: bool = ...,
    opener: _Opener | None = ...,
) -> AsyncIOWrapper[io.TextIOWrapper]: ...
@overload
async def open_file(
    file: _OpenFile,
    mode: OpenBinaryMode,
    buffering: Literal[0],
    encoding: None = ...,
    errors: None = ...,
    newline: None = ...,
    closefd: bool = ...,
    opener: _Opener | None = ...,
) -> AsyncIOWrapper[io.FileIO]: ...
@overload
async def open_file(
    file: _OpenFile,
    mode: OpenBinaryModeUpdating,
    buffering: Literal[-1, 1] = ...,
    encoding: None = ...,
    errors: None = ...,
    newline: None = ...,
    closefd: bool = ...,
    opener: _Opener | None = ...,
) -> AsyncIOWrapper[io.BufferedRandom]: ...
@overload
async def open_file(
    file: _OpenFile,
    mode: OpenBinaryModeWriting,
    buffering: Literal[-1, 1] = ...,
    encoding: None = ...,
    errors: None = ...,
    newline: None = ...,
    closefd: bool = ...,
    opener: _Opener | None = ...,
) -> AsyncIOWrapper[io.BufferedWriter]: ...
@overload
async def open_file(
    file: _OpenFile,
    mode: OpenBinaryModeReading,
    buffering: Literal[-1, 1] = ...,
    encoding: None = ...,
    errors: None = ...,
    newline: None = ...,
    closefd: bool = ...,
    opener: _Opener | None = ...,
) -> AsyncIOWrapper[io.BufferedReader]: ...
@overload
async def open_file(
    file: _OpenFile,
    mode: OpenBinaryMode,
    buffering: int,
    encoding: None = ...,
    errors: None = ...,
    newline: None = ...,
    closefd: bool = ...,
    opener: _Opener | None = ...,
) -> AsyncIOWrapper[BinaryIO]: ...

# Fallback if mode is not specified
@overload
async def open_file(
    file: _OpenFile,
    mode: str,
    buffering: int = ...,
    encoding: str | None = ...,
    errors: str | None = ...,
    newline: str | None = ...,
    closefd: bool = ...,
    opener: _Opener | None = ...,
) -> AsyncIOWrapper[IO[Any]]: ...


async def open_file(
    file: _OpenFile,
    mode: str = "r",
    buffering: int = -1,
    encoding: str | None = None,
    errors: str | None = None,
    newline: str | None = None,
    closefd: bool = True,
    opener: _Opener | None = None,
) -> AsyncIOWrapper:
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


def wrap_file(file: FileT) -> AsyncIOWrapper[FileT]:
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
