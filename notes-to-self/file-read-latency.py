import time

# https://bitbucket.org/pypy/pypy/issues/2624/weird-performance-on-pypy3-when-reading
# COUNT = 100000
# f = open("/etc/passwd", "rt")
COUNT = 1000000
# With default buffering this test never even syscalls, and goes at about ~140
# ns per call, instead of ~500 ns/call for the syscall and related overhead.
# That's probably more fair -- the BufferedIOBase code can't service random
# accesses, even if your working set fits entirely in RAM.
with open("/etc/passwd", "rb") as f:  # , buffering=0)
    while True:
        start = time.perf_counter()
        for _ in range(COUNT):
            f.seek(0)
            f.read(1)
        between = time.perf_counter()
        for _ in range(COUNT):
            f.seek(0)
        end = time.perf_counter()

        both = (between - start) / COUNT * 1e9
        seek = (end - between) / COUNT * 1e9
        read = both - seek
        print(
            f"{both:.2f} ns/(seek+read), {seek:.2f} ns/seek, estimate ~{read:.2f} ns/read"
        )
