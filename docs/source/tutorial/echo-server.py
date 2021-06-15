# echo-server.py

import trio
from itertools import count

# Port is arbitrary, but:
# - must be in between 1024 and 65535
# - can't be in use by some other program on your computer
# - must match what we set in our echo client
PORT = 12345

CONNECTION_COUNTER = count()

async def echo_server(server_stream):
    # Assign each connection a unique number to make our debug prints easier
    # to understand when there are multiple simultaneous connections.
    ident = next(CONNECTION_COUNTER)
    print(f"echo_server {ident}: started")
    try:
        async for data in server_stream:
            print(f"echo_server {ident}: received data {data!r}")
            await server_stream.send_all(data)
        print(f"echo_server {ident}: connection closed")
    # FIXME: add discussion of MultiErrors to the tutorial, and use
    # MultiError.catch here. (Not important in this case, but important if the
    # server code uses nurseries internally.)
    except Exception as exc:
        # Unhandled exceptions will propagate into our parent and take
        # down the whole program. If the exception is KeyboardInterrupt,
        # that's what we want, but otherwise maybe not...
        print(f"echo_server {ident}: crashed: {exc!r}")

async def main():
    await trio.serve_tcp(echo_server, PORT)

# We could also just write 'trio.run(trio.serve_tcp, echo_server, PORT)', but real
# programs almost always end up doing other stuff too and then we'd have to go
# back and factor it out into a separate function anyway. So it's simplest to
# just make it a standalone function from the beginning.
trio.run(main)
