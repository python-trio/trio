import trio
import os
import json
from itertools import count

# Experiment with generating Chrome Event Trace format, which can be browsed
# through chrome://tracing or other mechanisms.
#
# Screenshot: https://files.gitter.im/python-trio/general/fp6w/image.png
#
# Trace format docs: https://docs.google.com/document/d/1CvAClvFfyA5R-PhYUmn5OOQtYMH4h6I0nSsKchNAySU/preview#
#
# Things learned so far:
# - I don't understand how the ph="s"/ph="f" flow events work – I think
#   they're supposed to show up as arrows, and I'm emitting them between tasks
#   that wake each other up, but they're not showing up.
# - I think writing out json synchronously from each event is creating gaps in
#   the trace; maybe better to batch them up to write up all at once at the
#   end
# - including tracebacks would be cool
# - there doesn't seem to be any good way to group together tasks based on
#   nurseries. this really limits the value of this particular trace
#   format+viewer for us. (also maybe we should have an instrumentation event
#   when a nursery is opened/closed?)
# - task._counter should maybe be public
# - I don't know how to best show task lifetime, scheduling times, and what
#   the task is actually doing on the same plot. if we want to show particular
#   events like "called stream.send_all", then the chrome trace format won't
#   let us also show "task is running", because neither kind of event is
#   strictly nested inside the other

class Trace(trio.abc.Instrument):
    def __init__(self, out):
        self.out = out
        self.out.write("[\n")
        self.ids = count()
        self._task_metadata(-1, "I/O manager")

    def _write(self, **ev):
        ev.setdefault("pid", os.getpid())
        if ev["ph"] != "M":
            ev.setdefault("ts", trio.current_time() * 1e6)
        self.out.write(json.dumps(ev))
        self.out.write(",\n")

    def _task_metadata(self, tid, name):
        self._write(
            name="thread_name",
            ph="M",
            tid=tid,
            args={"name": name},
        )
        self._write(
            name="thread_sort_index",
            ph="M",
            tid=tid,
            args={"sort_index": tid},
        )

    def task_spawned(self, task):
        self._task_metadata(task._counter, task.name)
        self._write(
            name="task lifetime",
            ph="B",
            tid=task._counter,
        )

    def task_exited(self, task):
        self._write(
            name="task lifetime",
            ph="E",
            tid=task._counter,
        )

    def before_task_step(self, task):
        self._write(
            name="running",
            ph="B",
            tid=task._counter,
        )

    def after_task_step(self, task):
        self._write(
            name="running",
            ph="E",
            tid=task._counter,
        )

    def task_scheduled(self, task):
        try:
            waker = trio.hazmat.current_task()
        except RuntimeError:
            pass
        else:
            id = next(self.ids)
            self._write(
                ph="s",
                cat="wakeup",
                id=id,
                tid=waker._counter,
            )
            self._write(
                cat="wakeup",
                ph="f",
                id=id,
                tid=task._counter,
            )

    def before_io_wait(self, timeout):
        self._write(
            name=f"I/O wait",
            ph="B",
            tid=-1,
        )

    def after_io_wait(self, timeout):
        self._write(
            name=f"I/O wait",
            ph="E",
            tid=-1,
        )


async def child1():
    print("  child1: started! sleeping now...")
    await trio.sleep(1)
    print("  child1: exiting!")

async def child2():
    print("  child2: started! sleeping now...")
    await trio.sleep(1)
    print("  child2: exiting!")

async def parent():
    print("parent: started!")
    async with trio.open_nursery() as nursery:
        print("parent: spawning child1...")
        nursery.start_soon(child1)

        print("parent: spawning child2...")
        nursery.start_soon(child2)

        print("parent: waiting for children to finish...")
        # -- we exit the nursery block here --
    print("parent: all done!")

t = Trace(open("/tmp/t.json", "w"))
trio.run(parent, instruments=[t])
