import trio

async def run_test(nominal_backlog):
    print("--\nnominal:", nominal_backlog)

    listen_sock = trio.socket.socket()
    await listen_sock.bind(("127.0.0.1", 0))
    listen_sock.listen(nominal_backlog)
    client_socks = []
    while True:
        client_sock = trio.socket.socket()
        # Generally the response to the listen buffer being full is that the
        # SYN gets dropped, and the client retries after 1 second. So we
        # assume that any connect() call to localhost that takes >0.5 seconds
        # indicates a dropped SYN.
        with trio.move_on_after(0.5) as cancel_scope:
            await client_sock.connect(listen_sock.getsockname())
        if cancel_scope.cancelled_caught:
            break
        client_socks.append(client_sock)
    print("actual:", len(client_socks))
    for client_sock in client_socks:
        client_sock.close()

for nominal_backlog in [10, trio.socket.SOMAXCONN, 65535]:
    trio.run(run_test, nominal_backlog)
