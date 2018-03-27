import random
import trio
import contextvars

request_info = contextvars.ContextVar("request_info")


# Example logging function that tags each line with the request identifier.
def log(msg):
    # Read from task-local storage:
    request_tag = request_info.get()

    print("request {}: {}".format(request_tag, msg))


# An example "request handler" that does some work itself and also
# spawns some helper tasks to do some concurrent work.
async def handle_request(tag):
    # Write to task-local storage:
    request_info.set(tag)

    log("Request handler started")
    await trio.sleep(random.random())
    async with trio.open_nursery() as nursery:
        nursery.start_soon(concurrent_helper, "a")
        nursery.start_soon(concurrent_helper, "b")
    await trio.sleep(random.random())
    log("Request received finished")


async def concurrent_helper(job):
    log("Helper task {} started".format(job))
    await trio.sleep(random.random())
    log("Helper task {} finished".format(job))


# Spawn several "request handlers" simultaneously, to simulate a
# busy server handling multiple requests at the same time.
async def main():
    async with trio.open_nursery() as nursery:
        for i in range(3):
            nursery.start_soon(handle_request, i)


trio.run(main)
