import contextvars
import time

import trio

request_state = contextvars.ContextVar("request_state")

# Blocking function that should be run on a thread
# It could be reading or writing files, communicating with a database
# with a driver not compatible with async / await, etc.
def work_in_thread(msg):
    # Only use request_state.get() inside the worker thread
    state_value = request_state.get()
    current_user_id = state_value["current_user_id"]
    time.sleep(3)  # this would be some blocking call, like reading a file
    print(f"Processed user {current_user_id} with message {msg} in a thread worker")
    # Modify/mutate the state object, without setting the entire
    # contextvar with request_state.set()
    state_value["msg"] = msg


# An example "request handler" that does some work itself and also
# spawns some helper tasks in threads to execute blocking code.
async def handle_request(current_user_id):
    # Write to task-local storage:
    current_state = {"current_user_id": current_user_id, "msg": ""}
    request_state.set(current_state)

    # Here the current implicit contextvars context will be automatically copied
    # inside the worker thread
    await trio.to_thread.run_sync(work_in_thread, f"Hello {current_user_id}")
    # Extract the value set inside the thread in the same object stored in a contextvar
    new_msg = current_state["msg"]
    print(
        f"New contextvar value from worker thread for user {current_user_id}: {new_msg}"
    )


# Spawn several "request handlers" simultaneously, to simulate a
# busy server handling multiple requests at the same time.
async def main():
    async with trio.open_nursery() as nursery:
        for i in range(3):
            nursery.start_soon(handle_request, i)


trio.run(main)
