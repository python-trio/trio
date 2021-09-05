import pytest
import trio
from trio._dtls import DTLS
import random
import attr

import trustme
from OpenSSL import SSL

from .._core.tests.tutil import slow

ca = trustme.CA()
server_cert = ca.issue_cert("example.com")

server_ctx = SSL.Context(SSL.DTLS_METHOD)
server_cert.configure_cert(server_ctx)

client_ctx = SSL.Context(SSL.DTLS_METHOD)
ca.configure_trust(client_ctx)


async def test_smoke():
    server_sock = trio.socket.socket(type=trio.socket.SOCK_DGRAM)
    with server_sock:
        await server_sock.bind(("127.0.0.1", 0))
        server_dtls = DTLS(server_sock)

        async with trio.open_nursery() as nursery:

            async def handle_client(dtls_stream):
                await dtls_stream.do_handshake()
                assert await dtls_stream.receive() == b"hello"
                await dtls_stream.send(b"goodbye")

            await nursery.start(server_dtls.serve, server_ctx, handle_client)

            with trio.socket.socket(type=trio.socket.SOCK_DGRAM) as client_sock:
                client_dtls = DTLS(client_sock)
                client = await client_dtls.connect(
                    server_sock.getsockname(), client_ctx
                )
                await client.send(b"hello")
                assert await client.receive() == b"goodbye"
                nursery.cancel_scope.cancel()


@slow
async def test_handshake_over_terrible_network(autojump_clock):
    HANDSHAKES = 1000
    r = random.Random(0)
    fn = trio.testing.FakeNet()
    fn.enable()
    with trio.socket.socket(type=trio.socket.SOCK_DGRAM) as server_sock:
        async with trio.open_nursery() as nursery:

            async def route_packet(packet):
                while True:
                    op = r.choices(
                        ["deliver", "drop", "dupe", "delay"],
                        weights=[0.7, 0.1, 0.1, 0.1],
                    )[0]
                    print(f"{packet.source} -> {packet.destination}: {op}")
                    if op == "drop":
                        return
                    elif op == "dupe":
                        fn.send_packet(packet)
                    elif op == "delay":
                        await trio.sleep(r.random() * 3)
                    else:
                        assert op == "deliver"
                        print(
                            f"{packet.source} -> {packet.destination}: delivered {packet.payload.hex()}"
                        )
                        fn.deliver_packet(packet)
                        break

            def route_packet_wrapper(packet):
                try:
                    nursery.start_soon(route_packet, packet)
                except RuntimeError:
                    # We're exiting the nursery, so any remaining packets can just get
                    # dropped
                    pass

            fn.route_packet = route_packet_wrapper

            await server_sock.bind(("1.1.1.1", 54321))
            server_dtls = DTLS(server_sock)

            next_client_idx = 0
            next_client_msg_recvd = trio.Event()

            async def handle_client(dtls_stream):
                print("handling new client")
                try:
                    await dtls_stream.do_handshake()
                    while True:
                        data = await dtls_stream.receive()
                        print(f"server received plaintext: {data}")
                        if not data:
                            continue
                        assert int(data.decode()) == next_client_idx
                        next_client_msg_recvd.set()
                        break
                except trio.BrokenResourceError:
                    # client might have timed out on handshake and started a new one
                    # so we'll let this task die and let the new task do the check
                    print("new handshake restarting")
                    pass
                except:
                    print("server handler saw")
                    import traceback

                    traceback.print_exc()
                    raise

            await nursery.start(server_dtls.serve, server_ctx, handle_client)

            for _ in range(HANDSHAKES):
                print("#" * 80)
                print("#" * 80)
                print("#" * 80)
                with trio.socket.socket(type=trio.socket.SOCK_DGRAM) as client_sock:
                    client_dtls = DTLS(client_sock)
                    client = await client_dtls.connect(
                        server_sock.getsockname(), client_ctx
                    )
                    while True:
                        data = str(next_client_idx).encode()
                        print(f"client sending plaintext: {data}")
                        await client.send(data)
                        with trio.move_on_after(10) as cscope:
                            await next_client_msg_recvd.wait()
                        if not cscope.cancelled_caught:
                            break

                    next_client_idx += 1
                    next_client_msg_recvd = trio.Event()

            nursery.cancel_scope.cancel()
