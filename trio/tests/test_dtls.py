import pytest
import trio
import trio.testing
from trio import DTLSEndpoint
import random
import attr
from async_generator import asynccontextmanager
from itertools import count

import trustme
from OpenSSL import SSL

from trio.testing._fake_net import FakeNet
from .._core.tests.tutil import slow, binds_ipv6, gc_collect_harder

ca = trustme.CA()
server_cert = ca.issue_cert("example.com")

server_ctx = SSL.Context(SSL.DTLS_METHOD)
server_cert.configure_cert(server_ctx)

client_ctx = SSL.Context(SSL.DTLS_METHOD)
ca.configure_trust(client_ctx)


parametrize_ipv6 = pytest.mark.parametrize(
    "ipv6", [False, pytest.param(True, marks=binds_ipv6)], ids=["ipv4", "ipv6"]
)


def endpoint(**kwargs):
    ipv6 = kwargs.pop("ipv6", False)
    if ipv6:
        family = trio.socket.AF_INET6
    else:
        family = trio.socket.AF_INET
    sock = trio.socket.socket(type=trio.socket.SOCK_DGRAM, family=family)
    return DTLSEndpoint(sock, **kwargs)


@asynccontextmanager
async def dtls_echo_server(*, autocancel=True, mtu=None, ipv6=False):
    with endpoint(ipv6=ipv6) as server:
        if ipv6:
            localhost = "::1"
        else:
            localhost = "127.0.0.1"
        await server.socket.bind((localhost, 0))
        async with trio.open_nursery() as nursery:

            async def echo_handler(dtls_channel):
                print(
                    f"echo handler started: "
                    f"server {dtls_channel.endpoint.socket.getsockname()} "
                    f"client {dtls_channel.peer_address}"
                )
                if mtu is not None:
                    dtls_channel.set_ciphertext_mtu(mtu)
                try:
                    print("server starting do_handshake")
                    await dtls_channel.do_handshake()
                    print("server finished do_handshake")
                    async for packet in dtls_channel:
                        print(f"echoing {packet} -> {dtls_channel.peer_address}")
                        await dtls_channel.send(packet)
                except trio.BrokenResourceError:  # pragma: no cover
                    print("echo handler channel broken")

            await nursery.start(server.serve, server_ctx, echo_handler)

            yield server, server.socket.getsockname()

            if autocancel:
                nursery.cancel_scope.cancel()


@parametrize_ipv6
async def test_smoke(ipv6):
    async with dtls_echo_server(ipv6=ipv6) as (server_endpoint, address):
        with endpoint(ipv6=ipv6) as client_endpoint:
            client_channel = client_endpoint.connect(address, client_ctx)
            with pytest.raises(trio.NeedHandshakeError):
                client_channel.get_cleartext_mtu()

            await client_channel.do_handshake()
            await client_channel.send(b"hello")
            assert await client_channel.receive() == b"hello"
            await client_channel.send(b"goodbye")
            assert await client_channel.receive() == b"goodbye"

            with pytest.raises(ValueError):
                await client_channel.send(b"")

            client_channel.set_ciphertext_mtu(1234)
            cleartext_mtu_1234 = client_channel.get_cleartext_mtu()
            client_channel.set_ciphertext_mtu(4321)
            assert client_channel.get_cleartext_mtu() > cleartext_mtu_1234
            client_channel.set_ciphertext_mtu(1234)
            assert client_channel.get_cleartext_mtu() == cleartext_mtu_1234


@slow
async def test_handshake_over_terrible_network(autojump_clock):
    HANDSHAKES = 1000
    r = random.Random(0)
    fn = FakeNet()
    fn.enable()

    async with dtls_echo_server() as (_, address):
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
                    # I wanted to test random packet corruption too, but it turns out
                    # openssl has a bug in the following scenario:
                    #
                    # - client sends ClientHello
                    # - server sends HelloVerifyRequest with cookie -- but cookie is
                    #   invalid b/c either the ClientHello or HelloVerifyRequest was
                    #   corrupted
                    # - client re-sends ClientHello with invalid cookie
                    # - server replies with new HelloVerifyRequest and correct cookie
                    #
                    # At this point, the client *should* switch to the new, valid
                    # cookie. But OpenSSL doesn't; it stubbornly insists on re-sending
                    # the original, invalid cookie over and over. In theory we could
                    # work around this by detecting cookie changes and starting over
                    # with a whole new SSL object, but (a) it doesn't seem worth it, (b)
                    # when I tried then I ran into another issue where OpenSSL got stuck
                    # in an infinite loop sending alerts over and over, which I didn't
                    # dig into because see (a).
                    #
                    # elif op == "distort":
                    #     payload = bytearray(packet.payload)
                    #     payload[r.randrange(len(payload))] ^= 1 << r.randrange(8)
                    #     packet = attr.evolve(packet, payload=payload)
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
                except RuntimeError:  # pragma: no cover
                    # We're exiting the nursery, so any remaining packets can just get
                    # dropped
                    pass

            fn.route_packet = route_packet_wrapper

            for i in range(HANDSHAKES):
                print("#" * 80)
                print("#" * 80)
                print("#" * 80)
                with endpoint() as client_endpoint:
                    client = client_endpoint.connect(address, client_ctx)
                    print("client starting do_handshake")
                    await client.do_handshake()
                    print("client finished do_handshake")
                    msg = str(i).encode()
                    # Make multiple attempts to send data, because the network might
                    # drop it
                    while True:
                        with trio.move_on_after(10) as cscope:
                            await client.send(msg)
                            assert await client.receive() == msg
                        if not cscope.cancelled_caught:
                            break


async def test_implicit_handshake():
    async with dtls_echo_server() as (_, address):
        with endpoint() as client_endpoint:
            client = client_endpoint.connect(address, client_ctx)

            # Implicit handshake
            await client.send(b"xyz")
            assert await client.receive() == b"xyz"


async def test_full_duplex():
    # Tests simultaneous send/receive, and also multiple methods implicitly invoking
    # do_handshake simultaneously.
    with endpoint() as server_endpoint, endpoint() as client_endpoint:
        await server_endpoint.socket.bind(("127.0.0.1", 0))
        async with trio.open_nursery() as server_nursery:

            async def handler(channel):
                async with trio.open_nursery() as nursery:
                    nursery.start_soon(channel.send, b"from server")
                    nursery.start_soon(channel.receive)

            await server_nursery.start(server_endpoint.serve, server_ctx, handler)

            client = client_endpoint.connect(
                server_endpoint.socket.getsockname(), client_ctx
            )
            async with trio.open_nursery() as nursery:
                nursery.start_soon(client.send, b"from client")
                nursery.start_soon(client.receive)

            server_nursery.cancel_scope.cancel()


async def test_channel_closing():
    async with dtls_echo_server() as (_, address):
        with endpoint() as client_endpoint:
            client = client_endpoint.connect(address, client_ctx)
            await client.do_handshake()
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
        with endpoint() as client_endpoint:
            client1 = client_endpoint.connect(address1, client_ctx)
            client2 = client_endpoint.connect(address2, client_ctx)

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
                client_endpoint.connect(address1, client_ctx)

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

    with endpoint() as server_endpoint:
        await server_endpoint.socket.bind(("127.0.0.1", 0))
        async with trio.open_nursery() as nursery:
            await nursery.start(server_endpoint.serve, server_ctx, null_handler)
            with pytest.raises(trio.BusyResourceError):
                await nursery.start(server_endpoint.serve, server_ctx, null_handler)

            nursery.cancel_scope.cancel()

        async with trio.open_nursery() as nursery:
            await nursery.start(server_endpoint.serve, server_ctx, null_handler)
            nursery.cancel_scope.cancel()


async def test_connect_to_non_server(autojump_clock):
    fn = FakeNet()
    fn.enable()
    with endpoint() as client1, endpoint() as client2:
        await client1.socket.bind(("127.0.0.1", 0))
        # This should just time out
        with trio.move_on_after(100) as cscope:
            channel = client2.connect(client1.socket.getsockname(), client_ctx)
            await channel.do_handshake()
        assert cscope.cancelled_caught


async def test_incoming_buffer_overflow(autojump_clock):
    fn = FakeNet()
    fn.enable()
    for buffer_size in [10, 20]:
        async with dtls_echo_server() as (_, address):
            with endpoint(incoming_packets_buffer=buffer_size) as client_endpoint:
                assert client_endpoint.incoming_packets_buffer == buffer_size
                client = client_endpoint.connect(address, client_ctx)
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

    handshake_empty = encode_record(
        Record(
            content_type=ContentType.handshake,
            version=ProtocolVersion.DTLS10,
            epoch_seqno=0,
            payload=b"",
        )
    )

    client_hello_truncated_in_cookie = encode_record(
        Record(
            content_type=ContentType.handshake,
            version=ProtocolVersion.DTLS10,
            epoch_seqno=0,
            payload=bytes(2 + 32 + 1) + b"\xff",
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
                handshake_empty,
                client_hello_truncated_in_cookie,
            ]:
                await sock.sendto(bad_packet, address)
                await trio.sleep(1)


async def test_invalid_cookie_rejected(autojump_clock):
    fn = FakeNet()
    fn.enable()

    from trio._dtls import decode_client_hello_untrusted, BadPacket

    with trio.CancelScope() as cscope:

        # the first 11 bytes of ClientHello aren't protected by the cookie, so only test
        # corrupting bytes after that.
        offset_to_corrupt = count(11)

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
                with endpoint() as client:
                    channel = client.connect(address, client_ctx)
                    await channel.do_handshake()
            assert cscope.cancelled_caught


async def test_client_cancels_handshake_and_starts_new_one(autojump_clock):
    # if a client disappears during the handshake, and then starts a new handshake from
    # scratch, then the first handler's channel should fail, and a new handler get
    # started
    fn = FakeNet()
    fn.enable()

    with endpoint() as server, endpoint() as client:
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
                channel = client.connect(server.socket.getsockname(), client_ctx)
                await channel.do_handshake()
            assert connect_cscope.cancelled_caught

            print("client: starting second connect")
            channel = client.connect(server.socket.getsockname(), client_ctx)
            assert await channel.receive() == b"hello"

            # Give handlers a chance to finish
            await trio.sleep(10)
            nursery.cancel_scope.cancel()


async def test_swap_client_server():
    with endpoint() as a, endpoint() as b:
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

            b_to_a = b.connect(a.socket.getsockname(), client_ctx)
            await b_to_a.send(b"b as client")
            assert await b_to_a.receive() == b"b as client"

            a_to_b = a.connect(b.socket.getsockname(), client_ctx)
            await a_to_b.do_handshake()
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
        with endpoint() as client_endpoint:
            async with trio.open_nursery() as nursery:

                async def connecter():
                    client = client_endpoint.connect(address, client_ctx)
                    await client.do_handshake(initial_retransmit_timeout=1.5)
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


async def test_initial_retransmit_timeout_configuration(autojump_clock):
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
            with endpoint() as client:
                before = trio.current_time()
                blackholed = True
                channel = client.connect(address, client_ctx)
                await channel.do_handshake(initial_retransmit_timeout=t)
                after = trio.current_time()
                assert after - before == t


async def test_explicit_tiny_mtu_is_respected():
    # ClientHello is ~240 bytes, and it can't be fragmented, so our mtu has to
    # be larger than that. (300 is still smaller than any real network though.)
    MTU = 300

    fn = FakeNet()
    fn.enable()

    def route_packet(packet):
        print(f"delivering {packet}")
        print(f"payload size: {len(packet.payload)}")
        assert len(packet.payload) <= MTU
        fn.deliver_packet(packet)

    fn.route_packet = route_packet

    async with dtls_echo_server(mtu=MTU) as (server, address):
        with endpoint() as client:
            channel = client.connect(address, client_ctx)
            channel.set_ciphertext_mtu(MTU)
            await channel.do_handshake()
            await channel.send(b"hi")
            assert await channel.receive() == b"hi"


@parametrize_ipv6
async def test_handshake_handles_minimum_network_mtu(ipv6, autojump_clock):
    # Fake network that has the minimum allowable MTU for whatever protocol we're using.
    fn = FakeNet()
    fn.enable()

    if ipv6:
        mtu = 1280 - 48
    else:
        mtu = 576 - 28

    def route_packet(packet):
        if len(packet.payload) > mtu:
            print(f"dropping {packet}")
        else:
            print(f"delivering {packet}")
            fn.deliver_packet(packet)

    fn.route_packet = route_packet

    # See if we can successfully do a handshake -- some of the volleys will get dropped,
    # and the retransmit logic should detect this and back off the MTU to something
    # smaller until it succeeds.
    async with dtls_echo_server(ipv6=ipv6) as (_, address):
        with endpoint(ipv6=ipv6) as client_endpoint:
            client = client_endpoint.connect(address, client_ctx)
            # the handshake mtu backoff shouldn't affect the return value from
            # get_cleartext_mtu, b/c that's under the user's control via
            # set_ciphertext_mtu
            client.set_ciphertext_mtu(9999)
            await client.send(b"xyz")
            assert await client.receive() == b"xyz"
            assert client.get_cleartext_mtu() > 9000  # as vegeta said


@pytest.mark.filterwarnings("always:unclosed DTLS:ResourceWarning")
async def test_system_task_cleaned_up_on_gc():
    before_tasks = trio.lowlevel.current_statistics().tasks_living

    # We put this into a sub-function so that everything automatically becomes garbage
    # when the frame exits. For some reason just doing 'del e' wasn't enough on pypy
    # with coverage enabled -- I think we were hitting this bug:
    #     https://foss.heptapod.net/pypy/pypy/-/issues/3656
    async def start_and_forget_endpoint():
        e = endpoint()

        # This connection/handshake attempt can't succeed. The only purpose is to force
        # the endpoint to set up a receive loop.
        with trio.socket.socket(type=trio.socket.SOCK_DGRAM) as s:
            await s.bind(("127.0.0.1", 0))
            c = e.connect(s.getsockname(), client_ctx)
            async with trio.open_nursery() as nursery:
                nursery.start_soon(c.do_handshake)
                await trio.testing.wait_all_tasks_blocked()
                nursery.cancel_scope.cancel()

        during_tasks = trio.lowlevel.current_statistics().tasks_living
        return during_tasks

    with pytest.warns(ResourceWarning):
        during_tasks = await start_and_forget_endpoint()
        await trio.testing.wait_all_tasks_blocked()
        gc_collect_harder()

    await trio.testing.wait_all_tasks_blocked()

    after_tasks = trio.lowlevel.current_statistics().tasks_living
    assert before_tasks < during_tasks
    assert before_tasks == after_tasks


@pytest.mark.filterwarnings("always:unclosed DTLS:ResourceWarning")
async def test_gc_before_system_task_starts():
    e = endpoint()

    with pytest.warns(ResourceWarning):
        del e
        gc_collect_harder()

    await trio.testing.wait_all_tasks_blocked()


@pytest.mark.filterwarnings("always:unclosed DTLS:ResourceWarning")
async def test_gc_as_packet_received():
    fn = FakeNet()
    fn.enable()

    e = endpoint()
    await e.socket.bind(("127.0.0.1", 0))
    e._ensure_receive_loop()

    await trio.testing.wait_all_tasks_blocked()

    with trio.socket.socket(type=trio.socket.SOCK_DGRAM) as s:
        await s.sendto(b"xxx", e.socket.getsockname())
    # At this point, the endpoint's receive loop has been marked runnable because it
    # just received a packet; closing the endpoint socket won't interrupt that. But by
    # the time it wakes up to process the packet, the endpoint will be gone.
    with pytest.warns(ResourceWarning):
        del e
        gc_collect_harder()


@pytest.mark.filterwarnings("always:unclosed DTLS:ResourceWarning")
def test_gc_after_trio_exits():
    async def main():
        # We use fakenet just to make sure no real sockets can leak out of the test
        # case - on pypy somehow the socket was outliving the gc_collect_harder call
        # below. Since the test is just making sure DTLSEndpoint.__del__ doesn't explode
        # when called after trio exits, it doesn't need a real socket.
        fn = FakeNet()
        fn.enable()
        return endpoint()

    e = trio.run(main)
    with pytest.warns(ResourceWarning):
        del e
        gc_collect_harder()


async def test_already_closed_socket_doesnt_crash():
    with endpoint() as e:
        # We close the socket before checkpointing, so the socket will already be closed
        # when the system task starts up
        e.socket.close()
        # Now give it a chance to start up, and hopefully not crash
        await trio.testing.wait_all_tasks_blocked()


async def test_socket_closed_while_processing_clienthello(autojump_clock):
    fn = FakeNet()
    fn.enable()

    # Check what happens if the socket is discovered to be closed when sending a
    # HelloVerifyRequest, since that has its own sending logic
    async with dtls_echo_server() as (server, address):

        def route_packet(packet):
            fn.deliver_packet(packet)
            server.socket.close()

        fn.route_packet = route_packet

        with endpoint() as client_endpoint:
            with trio.move_on_after(10):
                client = client_endpoint.connect(address, client_ctx)
                await client.do_handshake()


async def test_association_replaced_while_handshake_running(autojump_clock):
    fn = FakeNet()
    fn.enable()

    def route_packet(packet):
        pass

    fn.route_packet = route_packet

    async with dtls_echo_server() as (_, address):
        with endpoint() as client_endpoint:
            c1 = client_endpoint.connect(address, client_ctx)
            async with trio.open_nursery() as nursery:

                async def doomed_handshake():
                    with pytest.raises(trio.BrokenResourceError):
                        await c1.do_handshake()

                nursery.start_soon(doomed_handshake)

                await trio.sleep(10)

                client_endpoint.connect(address, client_ctx)


async def test_association_replaced_before_handshake_starts():
    fn = FakeNet()
    fn.enable()

    # This test shouldn't send any packets
    def route_packet(packet):  # pragma: no cover
        assert False

    fn.route_packet = route_packet

    async with dtls_echo_server() as (_, address):
        with endpoint() as client_endpoint:
            c1 = client_endpoint.connect(address, client_ctx)
            client_endpoint.connect(address, client_ctx)
            with pytest.raises(trio.BrokenResourceError):
                await c1.do_handshake()


async def test_send_to_closed_local_port():
    # On Windows, sending a UDP packet to a closed local port can cause a weird
    # ECONNRESET error later, inside the receive task. Make sure we're handling it
    # properly.
    async with dtls_echo_server() as (_, address):
        with endpoint() as client_endpoint:
            async with trio.open_nursery() as nursery:
                for i in range(1, 10):
                    channel = client_endpoint.connect(("127.0.0.1", i), client_ctx)
                    nursery.start_soon(channel.do_handshake)
                channel = client_endpoint.connect(address, client_ctx)
                await channel.send(b"xxx")
                assert await channel.receive() == b"xxx"
                nursery.cancel_scope.cancel()
