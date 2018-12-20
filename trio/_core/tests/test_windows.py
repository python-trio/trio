import os
import tempfile
from contextlib import contextmanager

import pytest

on_windows = (os.name == "nt")
# Mark all the tests in this file as being windows-only
pytestmark = pytest.mark.skipif(not on_windows, reason="windows only")

from ... import _core, sleep, move_on_after
from ...testing import wait_all_tasks_blocked
if on_windows:
    from .._windows_cffi import (
        ffi, kernel32, INVALID_HANDLE_VALUE, raise_winerror, FileFlags
    )


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

        rawname = tfile.encode("utf-16le") + b"\0\0"
        rawname_buf = ffi.from_buffer(rawname)
        handle = kernel32.CreateFileW(
            ffi.cast("LPCWSTR", rawname_buf),
            FileFlags.GENERIC_READ,
            FileFlags.FILE_SHARE_READ,
            ffi.NULL,  # no security attributes
            FileFlags.OPEN_EXISTING,
            FileFlags.FILE_FLAG_OVERLAPPED,
            ffi.NULL,  # no template file
        )
        if handle == INVALID_HANDLE_VALUE:  # pragma: no cover
            raise_winerror()

        try:
            with memoryview(buffer) as buffer_view:

                async def read_region(start, end):
                    await _core.readinto_overlapped(
                        handle,
                        buffer_view[start:end],
                        start,
                    )

                # Make sure reading before the handle is registered
                # fails rather than hanging forever
                with pytest.raises(_core.TrioInternalError) as exc_info:
                    with move_on_after(0.5):
                        await read_region(0, 512)
                assert "Did you forget to call register_with_iocp()?" in str(
                    exc_info.value
                )

                _core.register_with_iocp(handle)

                async with _core.open_nursery() as nursery:
                    for start in range(0, 4096, 512):
                        nursery.start_soon(read_region, start, start + 512)

                assert buffer == data

                with pytest.raises(BufferError):
                    await _core.readinto_overlapped(handle, b"immutable")
        finally:
            kernel32.CloseHandle(handle)


@contextmanager
def pipe_with_overlapped_read():
    from asyncio.windows_utils import pipe
    import msvcrt

    read_handle, write_handle = pipe(overlapped=(True, False))
    _core.register_with_iocp(read_handle)
    try:
        write_fd = msvcrt.open_osfhandle(write_handle, 0)
        yield os.fdopen(write_fd, "wb", closefd=False), read_handle
    finally:
        kernel32.CloseHandle(ffi.cast("HANDLE", read_handle))
        kernel32.CloseHandle(ffi.cast("HANDLE", write_handle))


async def test_too_late_to_cancel():
    import time

    with pipe_with_overlapped_read() as (write_fp, read_handle):
        target = bytearray(6)
        async with _core.open_nursery() as nursery:
            # Start an async read in the background
            nursery.start_soon(_core.readinto_overlapped, read_handle, target)
            await wait_all_tasks_blocked()

            # Synchronous write to the other end of the pipe
            with write_fp:
                write_fp.write(b"test1\ntest2\n")

            # Note: not trio.sleep! We're making sure the OS level
            # ReadFile completes, before trio has a chance to execute
            # another checkpoint and notice it completed.
            time.sleep(1)
            nursery.cancel_scope.cancel()
        assert target[:6] == b"test1\n"

        # Do another I/O to make sure we've actually processed the
        # fallback completion that was posted when CancelIoEx failed.
        assert await _core.readinto_overlapped(read_handle, target) == 6
        assert target[:6] == b"test2\n"


# XX: test setting the iomanager._iocp to something weird to make
# sure that the IOCP thread can send exceptions back to the main thread.
# --> it's not clear if this is actually possible? we just get
# ERROR_INVALID_HANDLE which looks like the IOCP was closed (not an error)
