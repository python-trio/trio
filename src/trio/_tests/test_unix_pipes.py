from __future__ import annotations

import errno
import os
import select
import sys
from typing import TYPE_CHECKING

import pytest

from .. import _core
from .._core._tests.tutil import gc_collect_harder, skip_if_fbsd_pipes_broken
from ..testing import check_one_way_stream, wait_all_tasks_blocked

if TYPE_CHECKING:
    from .._file_io import _HasFileNo

posix = os.name == "posix"
pytestmark = pytest.mark.skipif(not posix, reason="posix only")

assert not TYPE_CHECKING or sys.platform == "unix"

if posix:
    from .._unix_pipes import FdStream


async def make_pipe() -> tuple[FdStream, FdStream]:
    """Makes a new pair of pipes."""
    (r, w) = os.pipe()
    return FdStream(w), FdStream(r)


async def make_clogged_pipe() -> tuple[FdStream, FdStream]:
    s, r = await make_pipe()
    try:
        while True:
            # We want to totally fill up the pipe buffer.
            # This requires working around a weird feature that POSIX pipes
            # have.
            # If you do a write of <= PIPE_BUF bytes, then it's guaranteed
            # to either complete entirely, or not at all. So if we tried to
            # write PIPE_BUF bytes, and the buffer's free space is only
            # PIPE_BUF/2, then the write will raise BlockingIOError... even
            # though a smaller write could still succeed! To avoid this,
            # make sure to write >PIPE_BUF bytes each time, which disables
            # the special behavior.
            # For details, search for PIPE_BUF here:
            #   http://pubs.opengroup.org/onlinepubs/9699919799/functions/write.html

            # for the getattr:
            # https://bitbucket.org/pypy/pypy/issues/2876/selectpipe_buf-is-missing-on-pypy3
            buf_size = getattr(select, "PIPE_BUF", 8192)
            os.write(s.fileno(), b"x" * buf_size * 2)
    except BlockingIOError:
        pass
    return s, r


async def test_send_pipe() -> None:
    r, w = os.pipe()
    async with FdStream(w) as send:
        assert send.fileno() == w
        await send.send_all(b"123")
        assert (os.read(r, 8)) == b"123"

        os.close(r)


async def test_receive_pipe() -> None:
    r, w = os.pipe()
    async with FdStream(r) as recv:
        assert (recv.fileno()) == r
        os.write(w, b"123")
        assert (await recv.receive_some(8)) == b"123"

        os.close(w)


async def test_pipes_combined() -> None:
    write, read = await make_pipe()
    count = 2**20

    async def sender() -> None:
        big = bytearray(count)
        await write.send_all(big)

    async def reader() -> None:
        await wait_all_tasks_blocked()
        received = 0
        while received < count:
            received += len(await read.receive_some(4096))

        assert received == count

    async with _core.open_nursery() as n:
        n.start_soon(sender)
        n.start_soon(reader)

    await read.aclose()
    await write.aclose()


async def test_pipe_errors() -> None:
    with pytest.raises(TypeError):
        FdStream(None)

    r, w = os.pipe()
    os.close(w)
    async with FdStream(r) as s:
        with pytest.raises(ValueError, match=r"^max_bytes must be integer >= 1$"):
            await s.receive_some(0)


async def test_del() -> None:
    w, r = await make_pipe()
    f1, f2 = w.fileno(), r.fileno()
    del w, r
    gc_collect_harder()

    with pytest.raises(OSError, match=r"Bad file descriptor$") as excinfo:
        os.close(f1)
    assert excinfo.value.errno == errno.EBADF

    with pytest.raises(OSError, match=r"Bad file descriptor$") as excinfo:
        os.close(f2)
    assert excinfo.value.errno == errno.EBADF


async def test_async_with() -> None:
    w, r = await make_pipe()
    async with w, r:
        pass

    assert w.fileno() == -1
    assert r.fileno() == -1

    with pytest.raises(OSError, match=r"Bad file descriptor$") as excinfo:
        os.close(w.fileno())
    assert excinfo.value.errno == errno.EBADF

    with pytest.raises(OSError, match=r"Bad file descriptor$") as excinfo:
        os.close(r.fileno())
    assert excinfo.value.errno == errno.EBADF


async def test_misdirected_aclose_regression() -> None:
    # https://github.com/python-trio/trio/issues/661#issuecomment-456582356
    w, r = await make_pipe()
    old_r_fd = r.fileno()

    # Close the original objects
    await w.aclose()
    await r.aclose()

    # Do a little dance to get a new pipe whose receive handle matches the old
    # receive handle.
    r2_fd, w2_fd = os.pipe()
    if r2_fd != old_r_fd:  # pragma: no cover
        os.dup2(r2_fd, old_r_fd)
        os.close(r2_fd)
    async with FdStream(old_r_fd) as r2:
        assert r2.fileno() == old_r_fd

        # And now set up a background task that's working on the new receive
        # handle
        async def expect_eof() -> None:
            assert await r2.receive_some(10) == b""

        async with _core.open_nursery() as nursery:
            nursery.start_soon(expect_eof)
            await wait_all_tasks_blocked()

            # Here's the key test: does calling aclose() again on the *old*
            # handle, cause the task blocked on the *new* handle to raise
            # ClosedResourceError?
            await r.aclose()
            await wait_all_tasks_blocked()

            # Guess we survived! Close the new write handle so that the task
            # gets an EOF and can exit cleanly.
            os.close(w2_fd)


async def test_close_at_bad_time_for_receive_some(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # We used to have race conditions where if one task was using the pipe,
    # and another closed it at *just* the wrong moment, it would give an
    # unexpected error instead of ClosedResourceError:
    # https://github.com/python-trio/trio/issues/661
    #
    # This tests what happens if the pipe gets closed in the moment *between*
    # when receive_some wakes up, and when it tries to call os.read
    async def expect_closedresourceerror() -> None:
        with pytest.raises(_core.ClosedResourceError):
            await r.receive_some(10)

    orig_wait_readable = _core._run.TheIOManager.wait_readable

    async def patched_wait_readable(
        self: _core._run.TheIOManager,
        fd: int | _HasFileNo,
    ) -> None:
        await orig_wait_readable(self, fd)
        await r.aclose()

    monkeypatch.setattr(_core._run.TheIOManager, "wait_readable", patched_wait_readable)
    s, r = await make_pipe()
    async with s, r:
        async with _core.open_nursery() as nursery:
            nursery.start_soon(expect_closedresourceerror)
            await wait_all_tasks_blocked()
            # Trigger everything by waking up the receiver
            await s.send_all(b"x")


async def test_close_at_bad_time_for_send_all(monkeypatch: pytest.MonkeyPatch) -> None:
    # We used to have race conditions where if one task was using the pipe,
    # and another closed it at *just* the wrong moment, it would give an
    # unexpected error instead of ClosedResourceError:
    # https://github.com/python-trio/trio/issues/661
    #
    # This tests what happens if the pipe gets closed in the moment *between*
    # when send_all wakes up, and when it tries to call os.write
    async def expect_closedresourceerror() -> None:
        with pytest.raises(_core.ClosedResourceError):
            await s.send_all(b"x" * 100)

    orig_wait_writable = _core._run.TheIOManager.wait_writable

    async def patched_wait_writable(
        self: _core._run.TheIOManager,
        fd: int | _HasFileNo,
    ) -> None:
        await orig_wait_writable(self, fd)
        await s.aclose()

    monkeypatch.setattr(_core._run.TheIOManager, "wait_writable", patched_wait_writable)
    s, r = await make_clogged_pipe()
    async with s, r:
        async with _core.open_nursery() as nursery:
            nursery.start_soon(expect_closedresourceerror)
            await wait_all_tasks_blocked()
            # Trigger everything by waking up the sender. On ppc64el, PIPE_BUF
            # is 8192 but make_clogged_pipe() ends up writing a total of
            # 1048576 bytes before the pipe is full, and then a subsequent
            # receive_some(10000) isn't sufficient for orig_wait_writable() to
            # return for our subsequent aclose() call. It's necessary to empty
            # the pipe further before this happens. So we loop here until the
            # pipe is empty to make sure that the sender wakes up even in this
            # case. Otherwise patched_wait_writable() never gets to the
            # aclose(), so expect_closedresourceerror() never returns, the
            # nursery never finishes all tasks and this test hangs.
            received_data = await r.receive_some(10000)
            while received_data:
                received_data = await r.receive_some(10000)


# On FreeBSD, directories are readable, and we haven't found any other trick
# for making an unreadable fd, so there's no way to run this test. Fortunately
# the logic this is testing doesn't depend on the platform, so testing on
# other platforms is probably good enough.
@pytest.mark.skipif(
    sys.platform.startswith("freebsd"),
    reason="no way to make read() return a bizarro error on FreeBSD",
)
async def test_bizarro_OSError_from_receive() -> None:
    # Make sure that if the read syscall returns some bizarro error, then we
    # get a BrokenResourceError. This is incredibly unlikely; there's almost
    # no way to trigger a failure here intentionally (except for EBADF, but we
    # exploit that to detect file closure, so it takes a different path). So
    # we set up a strange scenario where the pipe fd somehow transmutes into a
    # directory fd, causing os.read to raise IsADirectoryError (yes, that's a
    # real built-in exception type).
    s, r = await make_pipe()
    async with s, r:
        dir_fd = os.open("/", os.O_DIRECTORY, 0)
        try:
            os.dup2(dir_fd, r.fileno())
            with pytest.raises(_core.BrokenResourceError):
                await r.receive_some(10)
        finally:
            os.close(dir_fd)


@skip_if_fbsd_pipes_broken
async def test_pipe_fully() -> None:
    await check_one_way_stream(make_pipe, make_clogged_pipe)
