import pytest
import trio
from trio import DTLSEndpoint
import random
import attr
from contextlib import asynccontextmanager
from itertools import count

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

            with trio.socket.socket(
                type=trio.socket.SOCK_DGRAM, family=family
            ) as client_sock:
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


def dtls(**kwargs):
    sock = trio.socket.socket(type=trio.socket.SOCK_DGRAM)
    return DTLSEndpoint(sock, **kwargs)


@asynccontextmanager
async def dtls_echo_server(*, autocancel=True):
    with dtls() as server:
        await server.socket.bind(("127.0.0.1", 0))
        async with trio.open_nursery() as nursery:

            async def echo_handler(dtls_channel):
                print(
                    f"echo handler started: "
                    f"server {dtls_channel.endpoint.socket.getsockname()} "
                    f"client {dtls_channel.peer_address}"
                )
                async for packet in dtls_channel:
                    print(f"echoing {packet} -> {dtls_channel.peer_address}")
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

            client = await client_endpoint.connect(
                server_endpoint.socket.getsockname(), client_ctx
            )
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

            # close is idempotent
            client.close()
            # can also aclose
            await client.aclose()


async def test_serve_exits_cleanly_on_close():
    async with dtls_echo_server(autocancel=False) as (server_endpoint, address):
        server_endpoint.close()
        # Testing that the nursery exits even without being cancelled
    # close is idempotent
    server_endpoint.close()


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


async def test_double_serve():
    async def null_handler(_):  # pragma: no cover
        pass

    with dtls() as endpoint:
        async with trio.open_nursery() as nursery:
            await nursery.start(endpoint.serve, server_ctx, null_handler)
            with pytest.raises(trio.BusyResourceError):
                await nursery.start(endpoint.serve, server_ctx, null_handler)

            nursery.cancel_scope.cancel()

        async with trio.open_nursery() as nursery:
            await nursery.start(endpoint.serve, server_ctx, null_handler)
            nursery.cancel_scope.cancel()


async def test_connect_to_non_server(autojump_clock):
    fn = FakeNet()
    fn.enable()
    with dtls() as client1, dtls() as client2:
        await client1.socket.bind(("127.0.0.1", 0))
        # This should just time out
        with trio.move_on_after(100) as cscope:
            await client2.connect(client1.socket.getsockname(), client_ctx)
        assert cscope.cancelled_caught


async def test_incoming_buffer_overflow(autojump_clock):
    fn = FakeNet()
    fn.enable()
    for buffer_size in [10, 20]:
        async with dtls_echo_server() as (_, address):
            with dtls(incoming_packets_buffer=buffer_size) as client_endpoint:
                assert client_endpoint.incoming_packets_buffer == buffer_size
                client = await client_endpoint.connect(address, client_ctx)
                for i in range(buffer_size + 15):
                    await client.send(str(i).encode())
                    await trio.sleep(1)
                stats = client.statistics()
                assert stats.incoming_packets_dropped_in_trio == 15
                for i in range(buffer_size):
                    assert await client.receive() == str(i).encode()
                await client.send(b"buffer clear now")
                assert await client.receive() == b"buffer clear now"


async def test_server_socket_doesnt_crash_on_garbage(autojump_clock):
    fn = FakeNet()
    fn.enable()

    from trio._dtls import (
        Record,
        encode_record,
        HandshakeFragment,
        encode_handshake_fragment,
        ContentType,
        HandshakeType,
        ProtocolVersion,
    )

    client_hello = encode_record(
        Record(
            content_type=ContentType.handshake,
            version=ProtocolVersion.DTLS10,
            epoch_seqno=0,
            payload=encode_handshake_fragment(
                HandshakeFragment(
                    msg_type=HandshakeType.client_hello,
                    msg_len=10,
                    msg_seq=0,
                    frag_offset=0,
                    frag_len=10,
                    frag=bytes(10),
                )
            ),
        )
    )

    client_hello_extended = client_hello + b"\x00"
    client_hello_short = client_hello[:-1]
    # cuts off in middle of handshake message header
    client_hello_really_short = client_hello[:14]
    client_hello_corrupt_record_len = bytearray(client_hello)
    client_hello_corrupt_record_len[11] = 0xFF

    client_hello_fragmented = encode_record(
        Record(
            content_type=ContentType.handshake,
            version=ProtocolVersion.DTLS10,
            epoch_seqno=0,
            payload=encode_handshake_fragment(
                HandshakeFragment(
                    msg_type=HandshakeType.client_hello,
                    msg_len=20,
                    msg_seq=0,
                    frag_offset=0,
                    frag_len=10,
                    frag=bytes(10),
                )
            ),
        )
    )

    client_hello_trailing_data_in_record = encode_record(
        Record(
            content_type=ContentType.handshake,
            version=ProtocolVersion.DTLS10,
            epoch_seqno=0,
            payload=encode_handshake_fragment(
                HandshakeFragment(
                    msg_type=HandshakeType.client_hello,
                    msg_len=20,
                    msg_seq=0,
                    frag_offset=0,
                    frag_len=10,
                    frag=bytes(10),
                )
            )
            + b"\x00",
        )
    )
    async with dtls_echo_server() as (_, address):
        with trio.socket.socket(type=trio.socket.SOCK_DGRAM) as sock:
            for bad_packet in [
                b"",
                b"xyz",
                client_hello_extended,
                client_hello_short,
                client_hello_really_short,
                client_hello_corrupt_record_len,
                client_hello_fragmented,
                client_hello_trailing_data_in_record,
            ]:
                await sock.sendto(bad_packet, address)
                await trio.sleep(1)


async def test_invalid_cookie_rejected(autojump_clock):
    fn = FakeNet()
    fn.enable()

    from trio._dtls import decode_client_hello_untrusted, BadPacket

    with trio.CancelScope() as cscope:

        offset_to_corrupt = count()

        def route_packet(packet):
            try:
                _, cookie, _ = decode_client_hello_untrusted(packet.payload)
            except BadPacket:
                pass
            else:
                if len(cookie) != 0:
                    # this is a challenge response packet
                    # let's corrupt the next offset so the handshake should fail
                    payload = bytearray(packet.payload)
                    offset = next(offset_to_corrupt)
                    if offset >= len(payload):
                        # We've tried all offsets. Clamp offset to the end of the
                        # payload, and terminate the test.
                        offset = len(payload) - 1
                        cscope.cancel()
                    payload[offset] ^= 0x01
                    packet = attr.evolve(packet, payload=payload)

            fn.deliver_packet(packet)

        fn.route_packet = route_packet

        async with dtls_echo_server() as (_, address):
            while True:
                with dtls() as client:
                    await client.connect(address, client_ctx)
            assert cscope.cancelled_caught


async def test_client_cancels_handshake_and_starts_new_one(autojump_clock):
    # if a client disappears during the handshake, and then starts a new handshake from
    # scratch, then the first handler's channel should fail, and a new handler get
    # started
    fn = FakeNet()
    fn.enable()

    with dtls() as server, dtls() as client:
        await server.socket.bind(("127.0.0.1", 0))
        async with trio.open_nursery() as nursery:
            first_time = True

            async def handler(channel):
                nonlocal first_time
                if first_time:
                    first_time = False
                    print("handler: first time, cancelling connect")
                    connect_cscope.cancel()
                    await trio.sleep(0.5)
                    print("handler: handshake should fail now")
                    with pytest.raises(trio.BrokenResourceError):
                        await channel.do_handshake()
                else:
                    print("handler: not first time, sending hello")
                    await channel.send(b"hello")

            await nursery.start(server.serve, server_ctx, handler)

            print("client: starting first connect")
            with trio.CancelScope() as connect_cscope:
                await client.connect(server.socket.getsockname(), client_ctx)
            assert connect_cscope.cancelled_caught

            print("client: starting second connect")
            channel = await client.connect(server.socket.getsockname(), client_ctx)
            assert await channel.receive() == b"hello"

            nursery.cancel_scope.cancel()


async def test_swap_client_server():
    with dtls() as a, dtls() as b:
        await a.socket.bind(("127.0.0.1", 0))
        await b.socket.bind(("127.0.0.1", 0))

        async def echo_handler(channel):
            async for packet in channel:
                await channel.send(packet)

        async def crashing_echo_handler(channel):
            with pytest.raises(trio.BrokenResourceError):
                await echo_handler(channel)

        async with trio.open_nursery() as nursery:
            await nursery.start(a.serve, server_ctx, crashing_echo_handler)
            await nursery.start(b.serve, server_ctx, echo_handler)

            b_to_a = await b.connect(a.socket.getsockname(), client_ctx)
            await b_to_a.send(b"b as client")
            assert await b_to_a.receive() == b"b as client"

            a_to_b = await a.connect(b.socket.getsockname(), client_ctx)
            with pytest.raises(trio.BrokenResourceError):
                await b_to_a.send(b"association broken")
            await a_to_b.send(b"a as client")
            assert await a_to_b.receive() == b"a as client"

            nursery.cancel_scope.cancel()


@slow
async def test_openssl_retransmit_doesnt_break_stuff():
    # can't use autojump_clock here, because the point of the test is to wait for
    # openssl's built-in retransmit timer to expire, which is hard-coded to use
    # wall-clock time.
    fn = FakeNet()
    fn.enable()

    blackholed = True

    def route_packet(packet):
        if blackholed:
            print("dropped packet", packet)
            return
        print("delivered packet", packet)
        # packets.append(
        #     scapy.all.IP(
        #         src=packet.source.ip.compressed, dst=packet.destination.ip.compressed
        #     )
        #     / scapy.all.UDP(sport=packet.source.port, dport=packet.destination.port)
        #     / packet.payload
        # )
        fn.deliver_packet(packet)

    fn.route_packet = route_packet

    async with dtls_echo_server() as (server_endpoint, address):
        with dtls() as client_endpoint:
            async with trio.open_nursery() as nursery:

                async def connecter():
                    client = await client_endpoint.connect(
                        address, client_ctx, initial_retransmit_timeout=1.5
                    )
                    await client.send(b"hi")
                    assert await client.receive() == b"hi"

                nursery.start_soon(connecter)

                # openssl's default timeout is 1 second, so this ensures that it thinks
                # the timeout has expired
                await trio.sleep(1.1)
                # disable blackholing and send a garbage packet to wake up openssl so it
                # notices the timeout has expired
                blackholed = False
                await server_endpoint.socket.sendto(
                    b"xxx", client_endpoint.socket.getsockname()
                )
                # now the client task should finish connecting and exit cleanly

    # scapy.all.wrpcap("/tmp/trace.pcap", packets)


async def test_initial_retransmit_timeout(autojump_clock):
    fn = FakeNet()
    fn.enable()

    blackholed = True

    def route_packet(packet):
        nonlocal blackholed
        if blackholed:
            blackholed = False
        else:
            fn.deliver_packet(packet)

    fn.route_packet = route_packet

    async with dtls_echo_server() as (_, address):
        for t in [1, 2, 4]:
            with dtls() as client:
                before = trio.current_time()
                blackholed = True
                await client.connect(address, client_ctx, initial_retransmit_timeout=t)
                after = trio.current_time()
                assert after - before == t


async def test_tiny_mtu():
    async with dtls_echo_server() as (server, address):
        with dtls() as client:
            pass


# socket closed at terrible times
# garbage collecting DTLS object without closing it
# use fakenet, send a packet to the server, then immediately drop the dtls object and
# run gc before `sock.recvfrom()` can return

# ...connect() probably shouldn't do the handshake. makes it impossible to set MTU!
