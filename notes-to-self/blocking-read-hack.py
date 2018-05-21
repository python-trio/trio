import trio
import os
import socket
import errno

bad_socket = socket.socket()

class BlockingReadTimeoutError(Exception):
    pass

async def blocking_read_with_timeout(fd, count, timeout):
    print("reading from fd", fd)
    cancel_requested = False

    async def kill_it_after_timeout(new_fd):
        print("sleeping")
        await trio.sleep(timeout)
        print("breaking the fd")
        os.dup2(bad_socket.fileno(), new_fd, inheritable=False)
        # MAGIC
        print("setuid(getuid())")
        os.setuid(os.getuid())
        nonlocal cancel_requested
        cancel_requested = True

    new_fd = os.dup(fd)
    print("working fd is", new_fd)
    try:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(kill_it_after_timeout, new_fd)
            try:
                data = await trio.run_sync_in_worker_thread(os.read, new_fd, count)
            except OSError as exc:
                if cancel_requested and exc.errno == errno.ENOTCONN:
                    # Call was successfully cancelled. In a real version we'd
                    # integrate properly with trio's cancellation tools; here
                    # we'll just raise an arbitrary error.
                    raise BlockingReadTimeoutError from None
            print("got", data)
            nursery.cancel_scope.cancel()
            return data
    finally:
        os.close(new_fd)

trio.run(blocking_read_with_timeout, 0, 10, 2)
