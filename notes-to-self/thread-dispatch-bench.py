# Estimate the cost of simply passing some data into a thread and back, in as
# minimal a fashion as possible.
#
# This is useful to get a sense of the *lower-bound* cost of
# trio.to_thread.run_sync

import threading
import time
from queue import Queue

COUNT = 10000


def worker(in_q, out_q):
    while True:
        job = in_q.get()
        out_q.put(job())


def main():
    in_q = Queue()
    out_q = Queue()

    t = threading.Thread(target=worker, args=(in_q, out_q))
    t.start()

    while True:
        start = time.monotonic()
        for _ in range(COUNT):
            in_q.put(lambda: None)
            out_q.get()
        end = time.monotonic()
        print(f"{(end - start) / COUNT * 1e6:.2f} µs/job")


main()
