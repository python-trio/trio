import pytest
import trio
from trio import DTLSEndpoint
import random
import attr
from contextlib import asynccontextmanager

import trustme
from OpenSSL import SSL

from trio.testing._fake_net import FakeNet
from .._core.tests.tutil import slow, can_bind_ipv6

ca = trustme.CA()
server_cert = ca.issue_cert("example.com")

server_ctx = SSL.Context(SSL.DTLS_METHOD)
server_cert.configure_cert(server_ctx)

client_ctx = SSL.Context(SSL.DTLS_METHOD)
ca.configure_trust(client_ctx)


families = [trio.socket.AF_INET]
if can_bind_ipv6:
    families.append(trio.socket.AF_INET6)

@pytest.mark.parametrize("family", families)
async def test_smoke(family):
    if family == trio.socket.AF_INET:
        localhost = "127.0.0.1"
    else:
        localhost = "::1"
    server_sock = trio.socket.socket(type=trio.socket.SOCK_DGRAM, family=family)
    with server_sock:
        await server_sock.bind((localhost, 0))
        server_dtls = DTLSEndpoint(server_sock)

        async with trio.open_nursery() as nursery:

            async def handle_client(dtls_channel):
                await dtls_channel.do_handshake()
                assert await dtls_channel.receive() == b"hello"
                await dtls_channel.send(b"goodbye")

            await nursery.start(server_dtls.serve, server_ctx, handle_client)

            with trio.socket.socket(type=trio.socket.SOCK_DGRAM, family=family) as client_sock:
                client_dtls = DTLSEndpoint(client_sock)
                client = await client_dtls.connect(
                    server_sock.getsockname(), client_ctx
                )
                await client.send(b"hello")
                assert await client.receive() == b"goodbye"

                client.set_ciphertext_mtu(1234)
                cleartext_mtu_1234 = client.get_cleartext_mtu()
                client.set_ciphertext_mtu(4321)
                assert client.get_cleartext_mtu() > cleartext_mtu_1234
                client.set_ciphertext_mtu(1234)
                assert client.get_cleartext_mtu() == cleartext_mtu_1234

                nursery.cancel_scope.cancel()


@slow
async def test_handshake_over_terrible_network(autojump_clock):
    HANDSHAKES = 1000
    r = random.Random(0)
    fn = FakeNet()
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
            server_dtls = DTLSEndpoint(server_sock)

            next_client_idx = 0
            next_client_msg_recvd = trio.Event()

            async def handle_client(dtls_channel):
                print("handling new client")
                try:
                    await dtls_channel.do_handshake()
                    while True:
                        data = await dtls_channel.receive()
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
                    client_dtls = DTLSEndpoint(client_sock)
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


async def test_implicit_handshake():
    with trio.socket.socket(type=trio.socket.SOCK_DGRAM) as server_sock:
        await server_sock.bind(("127.0.0.1", 0))
        server_dtls = DTLSEndpoint(server_sock)


def dtls():
    sock = trio.socket.socket(type=trio.socket.SOCK_DGRAM)
    return DTLSEndpoint(sock)


@asynccontextmanager
async def dtls_echo_server(*, autocancel=True):
    with dtls() as server:
        await server.socket.bind(("127.0.0.1", 0))
        async with trio.open_nursery() as nursery:
            async def echo_handler(dtls_channel):
                async for packet in dtls_channel:
                    await dtls_channel.send(packet)

            await nursery.start(server.serve, server_ctx, echo_handler)

            yield server, server.socket.getsockname()

            if autocancel:
                nursery.cancel_scope.cancel()


async def test_implicit_handshake():
    async with dtls_echo_server() as (_, address):
        with dtls() as client_endpoint:
            client = await client_endpoint.connect(address, client_ctx)

            # Implicit handshake
            await client.send(b"xyz")
            assert await client.receive() == b"xyz"


async def test_full_duplex():
    with dtls() as server_endpoint, dtls() as client_endpoint:
        await server_endpoint.socket.bind(("127.0.0.1", 0))
        async with trio.open_nursery() as server_nursery:
            async def handler(channel):
                async with trio.open_nursery() as nursery:
                    nursery.start_soon(channel.send, b"from server")
                    nursery.start_soon(channel.receive)

            await server_nursery.start(server_endpoint.serve, server_ctx, handler)

            client = await client_endpoint.connect(server_endpoint.socket.getsockname(), client_ctx)
            async with trio.open_nursery() as nursery:
                nursery.start_soon(client.send, b"from client")
                nursery.start_soon(client.receive)

            server_nursery.cancel_scope.cancel()

async def test_channel_closing():
    async with dtls_echo_server() as (_, address):
        with dtls() as client_endpoint:
            client = await client_endpoint.connect(address, client_ctx)
            client.close()

            with pytest.raises(trio.ClosedResourceError):
                await client.send(b"abc")
            with pytest.raises(trio.ClosedResourceError):
                await client.receive()


async def test_serve_exits_cleanly_on_close():
    async with dtls_echo_server(autocancel=False) as (server_endpoint, address):
        server_endpoint.close()
        # Testing that the nursery exits even without being cancelled


async def test_client_multiplex():
    async with dtls_echo_server() as (_, address1), dtls_echo_server() as (_, address2):
        with dtls() as client_endpoint:
            client1 = await client_endpoint.connect(address1, client_ctx)
            client2 = await client_endpoint.connect(address2, client_ctx)

            await client1.send(b"abc")
            await client2.send(b"xyz")
            assert await client2.receive() == b"xyz"
            assert await client1.receive() == b"abc"

            client_endpoint.close()

            with pytest.raises(trio.ClosedResourceError):
                await client1.send("xxx")
            with pytest.raises(trio.ClosedResourceError):
                await client2.receive()
            with pytest.raises(trio.ClosedResourceError):
                await client_endpoint.connect(address1, client_ctx)

            async with trio.open_nursery() as nursery:
                with pytest.raises(trio.ClosedResourceError):
                    async def null_handler(_):  # pragma: no cover
                        pass
                    await nursery.start(client_endpoint.serve, server_ctx, null_handler)


async def test_dtls_over_dgram_only():
    with trio.socket.socket() as s:
        with pytest.raises(ValueError):
            DTLSEndpoint(s)


# incoming packets buffer overflow

# send all kinds of garbage at a server socket
# send hello at a client-only socket
# socket closed at terrible times
# cancelling a client handshake and then starting a new one
# garbage collecting DTLS object without closing it
# openssl retransmit
# receive a piece of garbage from the correct source during a handshake (corrupted
#   packet, someone being a jerk) -- though can't necessarily tolerate someone sending a
#   fake HelloRetryRequest
# calling serve twice
# connect() that replaces an existing association (currently totally broken!)
