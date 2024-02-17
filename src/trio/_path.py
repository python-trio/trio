from __future__ import annotations

import os
import pathlib
import sys
from functools import partial, update_wrapper
from typing import IO, TYPE_CHECKING, Any, BinaryIO, TypeVar, overload

from trio._file_io import AsyncIOWrapper, wrap_file
from trio._util import final
from trio.to_thread import run_sync

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable
    from io import BufferedRandom, BufferedReader, BufferedWriter, FileIO, TextIOWrapper

    from _typeshed import (
        OpenBinaryMode,
        OpenBinaryModeReading,
        OpenBinaryModeUpdating,
        OpenBinaryModeWriting,
        OpenTextMode,
    )
    from typing_extensions import Concatenate, Literal, ParamSpec

    P = ParamSpec("P")

    Self = TypeVar("Self", bound="Path")
    T = TypeVar("T")


def _wraps_async(
    wrapped: Callable[..., Any]
) -> Callable[[Callable[P, T]], Callable[P, Awaitable[T]]]:
    def decorator(fn: Callable[P, T]) -> Callable[P, Awaitable[T]]:
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return await run_sync(partial(fn, *args, **kwargs))

        update_wrapper(wrapper, wrapped)
        wrapper.__doc__ = (
            f"Like :meth:`~{wrapped.__module__}.{wrapped.__qualname__}`, but async."
        )
        return wrapper

    return decorator


def _wrap_method(
    fn: Callable[Concatenate[pathlib.Path, P], T],
) -> Callable[Concatenate[Path, P], Awaitable[T]]:
    @_wraps_async(fn)
    def wrapper(self: Path, /, *args: P.args, **kwargs: P.kwargs) -> T:
        return fn(pathlib.Path(self), *args, **kwargs)

    return wrapper


def _wrap_method_path(
    fn: Callable[Concatenate[pathlib.Path, P], pathlib.Path],
) -> Callable[Concatenate[Self, P], Awaitable[Self]]:
    @_wraps_async(fn)
    def wrapper(self: Self, /, *args: P.args, **kwargs: P.kwargs) -> Self:
        return self.__class__(fn(pathlib.Path(self), *args, **kwargs))

    return wrapper


def _wrap_method_path_iterable(
    fn: Callable[Concatenate[pathlib.Path, P], Iterable[pathlib.Path]],
) -> Callable[Concatenate[Self, P], Awaitable[Iterable[Self]]]:
    @_wraps_async(fn)
    def wrapper(self: Self, /, *args: P.args, **kwargs: P.kwargs) -> Iterable[Self]:
        return map(self.__class__, [*fn(pathlib.Path(self), *args, **kwargs)])

    assert wrapper.__doc__ is not None
    wrapper.__doc__ += f"""

    This is an async method that returns a synchronous iterator, so you
    use it like::

       for subpath in await mypath.{fn.__name__}():
           ...

    .. note::

        The iterator is loaded into memory immediately during the initial
        call, (see `issue #501
        <https://github.com/python-trio/trio/issues/501>`__ for discussion).
    """
    return wrapper


class Path(pathlib.PurePath):
    """A :class:`pathlib.Path` wrapper that executes blocking methods in
    :meth:`trio.to_thread.run_sync`.

    """

    __slots__ = ()

    def __new__(cls: type[Self], *args: str | os.PathLike[str]) -> Self:
        if cls is Path:
            cls = WindowsPath if os.name == "nt" else PosixPath  # type: ignore[assignment]
        return super().__new__(cls, *args)

    @classmethod
    @_wraps_async(pathlib.Path.cwd)
    def cwd(cls: type[Self]) -> Self:
        return cls(pathlib.Path.cwd())

    @classmethod
    @_wraps_async(pathlib.Path.home)
    def home(cls: type[Self]) -> Self:
        return cls(pathlib.Path.home())

    @overload
    async def open(
        self,
        mode: OpenTextMode = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> AsyncIOWrapper[TextIOWrapper]: ...

    @overload
    async def open(
        self,
        mode: OpenBinaryMode,
        buffering: Literal[0],
        encoding: None = None,
        errors: None = None,
        newline: None = None,
    ) -> AsyncIOWrapper[FileIO]: ...

    @overload
    async def open(
        self,
        mode: OpenBinaryModeUpdating,
        buffering: Literal[-1, 1] = -1,
        encoding: None = None,
        errors: None = None,
        newline: None = None,
    ) -> AsyncIOWrapper[BufferedRandom]: ...

    @overload
    async def open(
        self,
        mode: OpenBinaryModeWriting,
        buffering: Literal[-1, 1] = -1,
        encoding: None = None,
        errors: None = None,
        newline: None = None,
    ) -> AsyncIOWrapper[BufferedWriter]: ...

    @overload
    async def open(
        self,
        mode: OpenBinaryModeReading,
        buffering: Literal[-1, 1] = -1,
        encoding: None = None,
        errors: None = None,
        newline: None = None,
    ) -> AsyncIOWrapper[BufferedReader]: ...

    @overload
    async def open(
        self,
        mode: OpenBinaryMode,
        buffering: int = -1,
        encoding: None = None,
        errors: None = None,
        newline: None = None,
    ) -> AsyncIOWrapper[BinaryIO]: ...

    @overload
    async def open(  # type: ignore[misc]  # Any usage matches builtins.open().
        self,
        mode: str,
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> AsyncIOWrapper[IO[Any]]: ...

    @_wraps_async(pathlib.Path.open)  # type: ignore[misc]  # Overload return mismatch.
    def open(self, *args: Any, **kwargs: Any) -> AsyncIOWrapper[IO[Any]]:
        return wrap_file(pathlib.Path(self).open(*args, **kwargs))  # noqa: SIM115

    def __repr__(self) -> str:
        return f"trio.Path({str(self)!r})"

    stat = _wrap_method(pathlib.Path.stat)
    chmod = _wrap_method(pathlib.Path.chmod)
    exists = _wrap_method(pathlib.Path.exists)
    glob = _wrap_method_path_iterable(pathlib.Path.glob)
    rglob = _wrap_method_path_iterable(pathlib.Path.rglob)
    is_dir = _wrap_method(pathlib.Path.is_dir)
    is_file = _wrap_method(pathlib.Path.is_file)
    is_symlink = _wrap_method(pathlib.Path.is_symlink)
    is_socket = _wrap_method(pathlib.Path.is_socket)
    is_fifo = _wrap_method(pathlib.Path.is_fifo)
    is_block_device = _wrap_method(pathlib.Path.is_block_device)
    is_char_device = _wrap_method(pathlib.Path.is_char_device)
    if sys.version_info >= (3, 12):
        is_junction = _wrap_method(pathlib.Path.is_junction)
    iterdir = _wrap_method_path_iterable(pathlib.Path.iterdir)
    lchmod = _wrap_method(pathlib.Path.lchmod)
    lstat = _wrap_method(pathlib.Path.lstat)
    mkdir = _wrap_method(pathlib.Path.mkdir)
    if sys.platform != "win32":
        owner = _wrap_method(pathlib.Path.owner)
        group = _wrap_method(pathlib.Path.group)
    if sys.platform != "win32" or sys.version_info >= (3, 12):
        is_mount = _wrap_method(pathlib.Path.is_mount)
    if sys.version_info >= (3, 9):
        readlink = _wrap_method_path(pathlib.Path.readlink)
    rename = _wrap_method_path(pathlib.Path.rename)
    replace = _wrap_method_path(pathlib.Path.replace)
    resolve = _wrap_method_path(pathlib.Path.resolve)
    rmdir = _wrap_method(pathlib.Path.rmdir)
    symlink_to = _wrap_method(pathlib.Path.symlink_to)
    if sys.version_info >= (3, 10):
        hardlink_to = _wrap_method(pathlib.Path.hardlink_to)
    touch = _wrap_method(pathlib.Path.touch)
    unlink = _wrap_method(pathlib.Path.unlink)
    absolute = _wrap_method_path(pathlib.Path.absolute)
    expanduser = _wrap_method_path(pathlib.Path.expanduser)
    read_bytes = _wrap_method(pathlib.Path.read_bytes)
    read_text = _wrap_method(pathlib.Path.read_text)
    samefile = _wrap_method(pathlib.Path.samefile)
    write_bytes = _wrap_method(pathlib.Path.write_bytes)
    write_text = _wrap_method(pathlib.Path.write_text)
    if sys.version_info < (3, 12):
        link_to = _wrap_method(pathlib.Path.link_to)


@final
class PosixPath(Path, pathlib.PurePosixPath):
    """A :class:`pathlib.PosixPath` wrapper that executes blocking methods in
    :meth:`trio.to_thread.run_sync`.

    """

    __slots__ = ()


@final
class WindowsPath(Path, pathlib.PureWindowsPath):
    """A :class:`pathlib.WindowsPath` wrapper that executes blocking methods in
    :meth:`trio.to_thread.run_sync`.

    """

    __slots__ = ()


final(Path)
