import os
import tempfile

import pytest

on_windows = (os.name == "nt")
# Mark all the tests in this file as being windows-only
pytestmark = pytest.mark.skipif(not on_windows, reason="windows only")

from ... import _core
if on_windows:
    from .._windows_cffi import ffi, kernel32


# The undocumented API that this is testing should be changed to stop using
# UnboundedQueue (or just removed until we have time to redo it), but until
# then we filter out the warning.
@pytest.mark.filterwarnings(
    "ignore:.*UnboundedQueue:trio.TrioDeprecationWarning"
)
async def test_completion_key_listen():
    async def post(key):
        iocp = ffi.cast("HANDLE", _core.current_iocp())
        for i in range(10):
            print("post", i)
            if i % 3 == 0:
                await _core.checkpoint()
            success = kernel32.PostQueuedCompletionStatus(
                iocp, i, key, ffi.NULL
            )
            assert success

    with _core.monitor_completion_key() as (key, queue):
        async with _core.open_nursery() as nursery:
            nursery.start_soon(post, key)
            i = 0
            print("loop")
            async for batch in queue:  # pragma: no branch
                print("got some", batch)
                for info in batch:
                    assert info.lpOverlapped == 0
                    assert info.dwNumberOfBytesTransferred == i
                    i += 1
                if i == 10:
                    break
            print("end loop")


async def test_readinto_overlapped():
    data = b"1" * 1024 + b"2" * 1024 + b"3" * 1024 + b"4" * 1024
    buffer = bytearray(len(data))

    with tempfile.TemporaryDirectory() as tdir:
        tfile = os.path.join(tdir, "numbers.txt")
        with open(tfile, "wb") as fp:
            fp.write(data)
            fp.flush()

        rawname = tfile.encode("utf-16le")
        handle = kernel32.CreateFileW(
            ffi.cast("LPCWSTR", ffi.from_buffer(rawname)),
            0x80000000,  # GENERIC_READ
            0,  # no sharing
            ffi.NULL,  # no security attributes
            3,  # OPEN_EXISTING
            0x40000000,  # FILE_FLAG_OVERLAPPED
            ffi.NULL,  # no template file
        )
        _core.register_with_iocp(handle)

        async def read_region(start, end):
            await _core.readinto_overlapped(
                handle,
                memoryview(buffer)[start:end], start
            )

        try:
            async with _core.open_nursery() as nursery:
                for start in range(0, 4096, 512):
                    nursery.start_soon(read_region, start, start + 512)

            assert buffer == data

            with pytest.raises(TypeError):
                await _core.readinto_overlapped(handle, b"immutable")
        finally:
            kernel32.CloseHandle(handle)


# XX test setting the iomanager._iocp to something weird to make sure that the
# IOCP thread can send exceptions back to the main thread
