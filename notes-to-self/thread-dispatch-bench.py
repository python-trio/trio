# Estimate the cost of simply passing some data into a thread and back, in as
# minimal a fashion as possible.
#
# This is useful to get a sense of the *lower-bound* cost of
# run_sync_in_thread

import threading
from queue import Queue
import time

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
        print("{:.2f} µs/job".format((end - start) / COUNT * 1e6))

main()
