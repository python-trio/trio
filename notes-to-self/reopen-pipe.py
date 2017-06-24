import os
import threading
import time
import tempfile

def check_reopen(r1, w):
    try:
        print("Reopening read end")
        r2 = os.open("/proc/self/fd/{}".format(r1), os.O_RDONLY)

        print("r1 is {}, r2 is {}".format(r1, r2))

        print("checking they both can receive from w...")

        os.write(w, b"a")
        assert os.read(r1, 1) == b"a"

        os.write(w, b"b")
        assert os.read(r2, 1) == b"b"

        print("...ok")

        print("setting r2 to non-blocking")
        os.set_blocking(r2, False)

        print("os.get_blocking(r1) ==", os.get_blocking(r1))
        print("os.get_blocking(r2) ==", os.get_blocking(r2))

        # Check r2 is really truly non-blocking
        try:
            os.read(r2, 1)
        except BlockingIOError:
            print("r2 definitely seems to be in non-blocking mode")

        # Check that r1 is really truly still in blocking mode
        def sleep_then_write():
            time.sleep(1)
            os.write(w, b"c")
        threading.Thread(target=sleep_then_write, daemon=True).start()
        assert os.read(r1, 1) == b"c"
        print("r1 definitely seems to be in blocking mode")
    except Exception as exc:
        print("ERROR: {!r}".format(exc))


print("-- testing anonymous pipe --")
check_reopen(*os.pipe())

print("-- testing FIFO --")
with tempfile.TemporaryDirectory() as tmpdir:
    fifo = tmpdir + "/" + "myfifo"
    os.mkfifo(fifo)
    # "A process can open a FIFO in nonblocking mode.  In this case, opening
    # for read-only will succeed even if no-one has opened on the write side
    # yet and opening for write-only will fail with ENXIO (no such device or
    # address) unless the other end has already been opened." -- Linux fifo(7)
    r = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    assert not os.get_blocking(r)
    os.set_blocking(r, True)
    assert os.get_blocking(r)
    w = os.open(fifo, os.O_WRONLY)
    check_reopen(r, w)

print("-- testing socketpair --")
import socket
rs, ws = socket.socketpair()
check_reopen(rs.fileno(), ws.fileno())

