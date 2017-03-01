# echo-server-low-level.py

import trio

PORT = 12345
BUFSIZE = 65536  # arbitrary

async def echo_serve(sock):
    with sock:
        while True:
            data = await sock.recv(BUFSIZE)
            if not data:
                return
            await sock.sendall(data)

async def echo_listener(nursery):
    with trio.socket.socket() as listen_sock:
        listen_sock.setsockopt(
            trio.socket.SOL_SOCKET, trio.socket.SO_REUSEADDR, 1)
        listen_sock.bind(("127.0.0.1", PORT))
        listen_sock.listen(10)
        print("Echo server listening on 127.0.0.1:{}".format(PORT))
        while True:
            sock, _ = await listen_sock.accept()
            nursery.spawn(echo_serve, sock)

async def main():
    async with trio.open_nursery() as nursery:
        nursery.spawn(echo_listener, nursery)

trio.run(main)
