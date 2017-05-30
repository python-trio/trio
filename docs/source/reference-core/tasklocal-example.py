import random
import trio

request_info = trio.TaskLocal()

# Example logging function that tags each line with the request identifier.
def log(msg):
    # Read from task-local storage:
    request_tag = request_info.tag

    print("request {}: {}".format(request_tag, msg))

# An example "request handler" that does some work itself and also
# spawns some helper tasks to do some concurrent work.
async def handle_request(tag):
    # Write to task-local storage:
    request_info.tag = tag

    log("Request handler started")
    await trio.sleep(random.random())
    async with trio.open_nursery() as nursery:
        nursery.spawn(concurrent_helper, "a")
        nursery.spawn(concurrent_helper, "b")
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
            nursery.spawn(handle_request, i)

trio.run(main)
