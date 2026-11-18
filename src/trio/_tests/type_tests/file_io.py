"""Check the public types for Trio's asynchronous file wrappers."""

import io

import trio
from typing_extensions import assert_type


async def open_file_results(path: str) -> None:
    assert_type(await trio.open_file(path), trio.AsyncIOWrapper[io.TextIOWrapper])
    assert_type(
        await trio.open_file(path, "rb"),
        trio.AsyncIOWrapper[io.BufferedReader],
    )


def wrap_file_results(text: io.StringIO, binary: io.BytesIO) -> None:
    assert_type(trio.wrap_file(text), trio.AsyncIOWrapper[io.StringIO])
    assert_type(trio.wrap_file(binary), trio.AsyncIOWrapper[io.BytesIO])
