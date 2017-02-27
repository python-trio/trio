# tasks-with-trace.py

import trio

async def child1():
    print("  child1: started! sleeping now...")
    await trio.sleep(1)
    print("  child1: exiting!")

async def child2():
    print("  child2 started! sleeping now...")
    await trio.sleep(1)
    print("  child2 exiting!")

async def parent():
    print("parent: started!")
    async with trio.open_nursery() as nursery:
        print("parent: spawning child1...")
        nursery.spawn(child1)

        print("parent: spawning child2...")
        nursery.spawn(child2)

        print("parent: waiting for children to finish...")
        # -- we exit the nursery block here --
    print("parent: all done!")

class Tracer:
    def task_scheduled(self, task):
        print("### task scheduled:", task)

    def before_task_step(self, task):
        print("### task about to run:", task)

    def after_task_step(self, task):
        print("### task paused:", task)

trio.run(parent, instruments=[Tracer()])
