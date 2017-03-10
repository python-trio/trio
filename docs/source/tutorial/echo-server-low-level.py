# echo-server-low-level.py

import trio

# Port is arbitrary, but:
# - must be in between 1024 and 65535
# - can't be in use by some other program on your computer
# - must match what we set in our echo client
PORT = 12345
# How much memory to spend (at most) on each call to recv. Pretty arbitrary,
# but shouldn't be too big or too small.
BUFSIZE = 16384

async def echo_server(server_sock, ident):
    with server_sock:
        print("echo_server {}: started".format(ident))
        try:
            while True:
                data = await server_sock.recv(BUFSIZE)
                print("echo_server {}: received data {!r}".format(ident, data))
                if not data:
                    print("echo_server {}: connection closed".format(ident))
                    return
                print("echo_server {}: sending data {!r}".format(ident, data))
                await server_sock.sendall(data)
        except Exception as exc:
            # Unhandled exceptions will propagate into our parent and take
            # down the whole program. If the exception is KeyboardInterrupt,
            # that's what we want, but otherwise maybe not...
            print("echo_server {}: crashed: {!r}".format(ident, exc))

async def echo_listener(nursery):
    with trio.socket.socket() as listen_sock:
        # Notify the operating system that we want to receive connection
        # attempts at this address:
        listen_sock.bind(("127.0.0.1", PORT))
        listen_sock.listen()
        print("echo_listener: listening on 127.0.0.1:{}".format(PORT))

        ident = 0
        while True:
            server_sock, _ = await listen_sock.accept()
            print("echo_listener: got new connection, spawning echo_server")
            ident += 1
            nursery.spawn(echo_server, server_sock, ident)

async def parent():
    async with trio.open_nursery() as nursery:
        print("parent: spawning echo_listener")
        nursery.spawn(echo_listener, nursery)

trio.run(parent)
