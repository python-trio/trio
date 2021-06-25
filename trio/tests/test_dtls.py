import trio
from trio._dtls import DTLS

import trustme
from OpenSSL import SSL

ca = trustme.CA()
server_cert = ca.issue_cert("example.com")

server_ctx = SSL.Context(SSL.DTLS_METHOD)
server_cert.configure_cert(server_ctx)

client_ctx = SSL.Context(SSL.DTLS_METHOD)
ca.configure_trust(client_ctx)

# XX this should be handled in the real code
server_ctx.set_options(SSL.OP_NO_QUERY_MTU | SSL.OP_NO_RENEGOTIATION)
client_ctx.set_options(SSL.OP_NO_QUERY_MTU | SSL.OP_NO_RENEGOTIATION)

async def test_smoke():
    server_sock = trio.socket.socket(type=trio.socket.SOCK_DGRAM)
    with server_sock:
        await server_sock.bind(("127.0.0.1", 54321))
        server_dtls = DTLS(server_sock)

        async with trio.open_nursery() as nursery:

            async def handle_client(dtls_stream):
                await dtls_stream.do_handshake()
                assert await dtls_stream.receive() == b"hello"
                await dtls_stream.send(b"goodbye")

            await nursery.start(server_dtls.serve, server_ctx, handle_client)

            client_sock = trio.socket.socket(type=trio.socket.SOCK_DGRAM)
            client_dtls = DTLS(client_sock)
            client = await client_dtls.connect(server_sock.getsockname(), client_ctx)
            await client.send(b"hello")
            assert await client.receive() == b"goodbye"
            nursery.cancel_scope.cancel()
