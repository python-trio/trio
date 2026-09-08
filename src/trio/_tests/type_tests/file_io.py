"""File wrappers can be annotated using the public generic type."""

import io

import trio
from trio import AsyncIOWrapper
from typing_extensions import assert_type


async def open_results(path: str) -> None:
    async with await trio.open_file(path) as text_file:
        assert_type(text_file, AsyncIOWrapper[io.TextIOWrapper])
        assert_type(await text_file.read(), str)
    async with await trio.open_file(path, "rb") as binary_file:
        assert_type(binary_file, AsyncIOWrapper[io.BufferedReader])
        assert_type(await binary_file.read(), bytes)
    async with await trio.open_file(path, "rb", buffering=0) as raw_file:
        assert_type(raw_file, AsyncIOWrapper[io.FileIO])


async def wrapped_results(text: io.StringIO, binary: io.BytesIO) -> None:
    async with trio.wrap_file(text) as text_file:
        assert_type(text_file, AsyncIOWrapper[io.StringIO])
        assert_type(text_file.wrapped, io.StringIO)
        assert_type(await text_file.read(), str)
    async with trio.wrap_file(binary) as binary_file:
        assert_type(binary_file, AsyncIOWrapper[io.BytesIO])
        assert_type(binary_file.wrapped, io.BytesIO)
        assert_type(await binary_file.read(), bytes)
