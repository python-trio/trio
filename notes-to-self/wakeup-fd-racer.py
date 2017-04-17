import os
import signal
import threading
import time
import socket
import select
import itertools

# Equivalent to the C function raise(), which Python doesn't wrap
if os.name == "nt":
    import cffi
    _ffi = cffi.FFI()
    _ffi.cdef("int raise(int);")
    _lib = _ffi.dlopen("api-ms-win-crt-runtime-l1-1-0.dll")
    signal_raise = getattr(_lib, "raise")
else:
    def signal_raise(signum):
        # Use pthread_kill to make sure we're actually using the wakeup fd on
        # Unix
        signal.pthread_kill(threading.get_ident(), signum)


def raise_SIGINT_soon():
    time.sleep(1)
    signal_raise(signal.SIGINT)
    # Sending 2 signals becomes reliable, as we'd expect (because we need
    # set-flags -> write-to-fd, and doing it twice does
    # write-to-fd -> set-flags -> write-to-fd -> set-flags)
    #signal_raise(signal.SIGINT)


def drain(sock):
    total = 0
    try:
        while True:
            total += len(sock.recv(1024))
    except BlockingIOError:
        pass
    return total


def main():
    writer, reader = socket.socketpair()
    writer.setblocking(False)
    reader.setblocking(False)

    signal.set_wakeup_fd(writer.fileno())

    # Keep trying until we lose the race...
    for attempt in itertools.count():
        print(f"Attempt {attempt}: start")

        # Make sure the socket is empty
        drained = drain(reader)
        if drained:
            print(f"Attempt {attempt}: ({drained} residual bytes discarded)")

        # Arrange for SIGINT to be delivered 1 second from now
        thread = threading.Thread(target=raise_SIGINT_soon)
        thread.start()

        # Fake an IO loop that's trying to sleep for 10 seconds (but will
        # hopefully get interrupted after just 1 second)
        start = time.monotonic()
        target = start + 10
        try:
            select_calls = 0
            drained = 0
            while True:
                now = time.monotonic()
                if now > target:
                    break
                select_calls += 1
                r, _, _ = select.select([reader], [], [], target - now)
                if r:
                    # In theory we should loop to fully drain the socket but
                    # honestly there's 1 byte in there at most and it'll be
                    # fine.
                    drained += drain(reader)
        except KeyboardInterrupt:
            pass
        else:
            print(f"Attempt {attempt}: no KeyboardInterrupt?!")

        # We expect a successful run to take 1 second, and a failed run to
        # take 10 seconds, so 2 seconds is a reasonable cutoff to distinguish
        # them.
        duration = time.monotonic() - start
        if duration < 2:
            print(f"Attempt {attempt}: OK, trying again "
                  f"(select_calls = {select_calls}, drained = {drained})")
        else:
            print(f"Attempt {attempt}: FAILED, took {duration} seconds")
            print(f"select_calls = {select_calls}, drained = {drained}")
            break

        thread.join()

if __name__ == "__main__":
    main()
