# echo-client-low-level.py

import sys
import trio

# arbitrary, but:
# - must be in between 1024 and 65535
# - can't be in use by some other program on your computer
# - must match what we set in our echo client
PORT = 12345
# How much memory to spend (at most) on each call to recv. Pretty arbitrary,
# but shouldn't be too big or too small.
BUFSIZE = 16384

async def sender(client_sock):
    print("sender: started!")
    while True:
        data = b"async can sometimes be confusing, but I believe in you!"
        print("sender: sending {!r}".format(data))
        await client_sock.sendall(data)
        await trio.sleep(1)

async def receiver(client_sock):
    print("receiver: started!")
    while True:
        data = await client_sock.recv(BUFSIZE)
        print("receiver: got data {!r}".format(data))
        if not data:
            print("receiver: connection closed")
            sys.exit()

async def parent():
    print("parent: connecting to 127.0.0.1:{}".format(PORT))
    with trio.socket.socket() as client_sock:
        await client_sock.connect(("127.0.0.1", PORT))
        async with trio.open_nursery() as nursery:
            print("parent: spawning sender...")
            nursery.spawn(sender, client_sock)

            print("parent: spawning receiver...")
            nursery.spawn(receiver, client_sock)

trio.run(parent)
