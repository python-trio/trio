import pytest

from pathlib import Path
import threading
import socket as stdlib_socket
import ssl as stdlib_ssl
from contextlib import contextmanager

from OpenSSL import SSL

import trio
from .. import _core
from .. import ssl as tssl
from .. import socket as tsocket
from .._util import UnLock

from .._core.tests.tutil import slow

from ..testing import assert_yields, wait_all_tasks_blocked


ASSETS_DIR = Path(__file__).parent / "test_ssl_certs"
CA = str(ASSETS_DIR / "trio-test-CA.pem")
CERT1 = str(ASSETS_DIR / "trio-test-1.pem")


# We have two different kinds of echo server fixtures we use for testing. The
# first is a real server written using the stdlib ssl module and blocking
# sockets. It runs in a thread and we talk to it over a real socketpair(), to
# validate interoperability in a semi-realistic setting.
#
# The second is a very weird virtual echo server that lives inside a custom
# Stream class. It lives entirely inside the Python object space; there are no
# operating system calls in it at all. No threads, no I/O, nothing. It's
# 'sendall' call takes encrypted data from a client and feeds it directly into
# the server-side TLS state engine to decrypt, then takes that data, feeds it
# back through to get the encrypted response, and returns it from 'recv'. This
# gives us full control and reproducibility. This server is written using
# PyOpenSSL, so that we can trigger renegotiations on demand. It also allows
# us to insert random (virtual) delays, to really exercise all the weird paths
# in SSLStream's state engine.
#
# Both present a certificate for "trio-test-1.example.org", that's signed by
# trio-test-CA.pem, an extremely trustworthy CA.


SERVER_CTX = stdlib_ssl.create_default_context(
    stdlib_ssl.Purpose.CLIENT_AUTH,
)
SERVER_CTX.load_cert_chain(CERT1)

# The blocking socket server.
def ssl_echo_serve_sync(sock, *, expect_fail=False):
    try:
        wrapped = SERVER_CTX.wrap_socket(sock, server_side=True)
        wrapped.do_handshake()
        while True:
            data = wrapped.recv(4096)
            if not data:
                # graceful shutdown
                wrapped.unwrap()
                return
            wrapped.sendall(data)
    except Exception as exc:
        if expect_fail:
            print("ssl_echo_serve_sync got error as expected:", exc)
        else:  # pragma: no cover
            raise
    else:
        if expect_fail:  # pragma: no cover
            print("failed to fail?!")


# Fixture that gives a raw socket connected to a trio-test-1 echo server
# (running in a thread). Useful for testing making connections with different
# SSLContexts.
@contextmanager
def ssl_echo_server_raw(**kwargs):
    a, b = stdlib_socket.socketpair()
    with a, b:
        t = threading.Thread(
            target=ssl_echo_serve_sync,
            args=(b,),
            kwargs=kwargs,
        )
        t.start()

        yield tsocket.from_stdlib_socket(a)

    # exiting the context manager closes the sockets, which should force the
    # thread to shut down (possibly with an error)
    t.join()


# Fixture that gives a properly set up SSLStream connected to a trio-test-1
# echo server (running in a thread)
@contextmanager
def ssl_echo_server(**kwargs):
    with ssl_echo_server_raw(**kwargs) as sock:
        client_ctx = stdlib_ssl.create_default_context(cafile=CA)
        yield tssl.SSLStream(
            sock, client_ctx, server_hostname="trio-test-1.example.org")


# The weird ... in-memory server thing.
# Doesn't inherit from Stream because I left out the methods that we don't
# actually need.
class PyOpenSSLEchoStream:
    def __init__(self, sleeper=None):
        ctx = SSL.Context(SSL.TLSv1_2_METHOD)
        ctx.use_certificate_file(CERT1)
        ctx.use_privatekey_file(CERT1)
        self._conn = SSL.Connection(ctx, None)
        self._conn.set_accept_state()
        self._lot = _core.ParkingLot()
        self._pending_cleartext = bytearray()

        self._sendall_mutex = UnLock(
            RuntimeError, "simultaneous calls to PyOpenSSLEchoStream.sendall")
        self._recv_mutex = UnLock(
            RuntimeError, "simultaneous calls to PyOpenSSLEchoStream.recv")

        if sleeper is None:
            async def no_op_sleeper(_):
                return
            self.sleeper = no_op_sleeper
        else:
            self.sleeper = sleeper

    def forceful_close(self):
        self._conn.bio_shutdown()

    async def graceful_close(self):
        self.forceful_close()

    def renegotiate_pending(self):
        return self._conn.renegotiate_pending()

    def renegotiate(self):
        # Returns false if a renegotation is already in progress, meaning
        # nothing happens.
        assert self._conn.renegotiate()

    async def wait_sendall_might_not_block(self):
        await _core.yield_briefly()
        await self.sleeper("wait_sendall_might_not_block")

    async def sendall(self, data):
        print("  --> wrapped_stream.sendall")
        with self._sendall_mutex:
            await _core.yield_briefly()
            await self.sleeper("sendall")
            self._conn.bio_write(data)
            while True:
                await self.sleeper("sendall")
                try:
                    data = self._conn.recv(1)
                except SSL.ZeroReturnError:
                    self._conn.shutdown()
                    print("renegotiations:", self._conn.total_renegotiations())
                    break
                except SSL.WantReadError:
                    break
                else:
                    self._pending_cleartext += data
            self._lot.unpark_all()
            await self.sleeper("sendall")
            print("  <-- wrapped_stream.sendall finished")

    async def recv(self, nbytes):
        print("  --> wrapped_stream.recv")
        with self._recv_mutex:
            try:
                await _core.yield_briefly()
                while True:
                    await self.sleeper("recv")
                    try:
                        return self._conn.bio_read(nbytes)
                    except SSL.WantReadError:
                        # No data in our ciphertext buffer; try to generate
                        # some.
                        if self._pending_cleartext:
                            # We have some cleartext; maybe we can encrypt it
                            # and then return it.
                            print("    trying", self._pending_cleartext)
                            try:
                                # PyOpenSSL bug: doesn't accept bytearray
                                # https://github.com/pyca/pyopenssl/issues/621
                                next_byte = self._pending_cleartext[0:1]
                                self._conn.send(bytes(next_byte))
                            except SSL.WantReadError:
                                # We didn't manage to send the cleartext (and
                                # in particular we better leave it there to
                                # try again, due to openssl's retry
                                # semantics), but it's possible we pushed a
                                # renegotiation forward and *now* we have data
                                # to send.
                                try:
                                    return self._conn.bio_read(nbytes)
                                except SSL.WantReadError:
                                    # Nope. We're just going to have to wait
                                    # for someone to call sendall() to give
                                    # use more data.
                                    print("parking (a)")
                                    await self._lot.park()
                            else:
                                # We successfully sent that byte, so we don't
                                # have to again.
                                del self._pending_cleartext[0:1]
                        else:
                            # no pending cleartext; nothing to do but wait for
                            # someone to call sendall
                            print("parking (b)")
                            await self._lot.park()
            finally:
                await self.sleeper("recv")
                print("  <-- wrapped_stream.recv finished")


async def test_PyOpenSSLEchoStream_gives_resource_busy_errors():
    # Make sure that PyOpenSSLEchoStream complains if two tasks call sendall
    # at the same time, or ditto for recv. The tricky cases where SSLStream
    # might accidentally do this are during renegotation, which we test using
    # PyOpenSSLEchoStream, so this makes sure that if we do have a bug then
    # PyOpenSSLEchoStream will notice and complain.

    s = PyOpenSSLEchoStream()
    with pytest.raises(RuntimeError) as excinfo:
        async with _core.open_nursery() as nursery:
            nursery.spawn(s.sendall, b"x")
            nursery.spawn(s.sendall, b"x")
    assert "simultaneous" in str(excinfo.value)

    s = PyOpenSSLEchoStream()
    with pytest.raises(RuntimeError) as excinfo:
        async with _core.open_nursery() as nursery:
            nursery.spawn(s.recv, 1)
            nursery.spawn(s.recv, 1)
    assert "simultaneous" in str(excinfo.value)


@contextmanager
def virtual_ssl_echo_server(**kwargs):
    client_ctx = tssl.create_default_context(cafile=CA)
    fakesock = PyOpenSSLEchoStream(**kwargs)
    yield tssl.SSLStream(
        fakesock, client_ctx, server_hostname="trio-test-1.example.org")


# Simple smoke test for handshake/send/receive/shutdown talking to a
# synchronous server, plus make sure that we do the bare minimum of
# certificate checking (even though this is really Python's responsibility)
async def test_ssl_client_basics():
    # Everything OK
    with ssl_echo_server() as s:
        assert not s.server_side
        await s.sendall(b"x")
        assert await s.recv(1) == b"x"
        await s.graceful_close()

    # Didn't configure the CA file, should fail
    with ssl_echo_server_raw(expect_fail=True) as sock:
        client_ctx = stdlib_ssl.create_default_context()
        s = tssl.SSLStream(
            sock, client_ctx, server_hostname="trio-test-1.example.org")
        assert not s.server_side
        with pytest.raises(tssl.SSLError):
            await s.sendall(b"x")

    # Trusted CA, but wrong host name
    with ssl_echo_server_raw(expect_fail=True) as sock:
        client_ctx = stdlib_ssl.create_default_context(cafile=CA)
        s = tssl.SSLStream(
            sock, client_ctx, server_hostname="trio-test-2.example.org")
        assert not s.server_side
        with pytest.raises(tssl.CertificateError):
            await s.sendall(b"x")


async def test_ssl_server_basics():
    a, b = stdlib_socket.socketpair()
    with a, b:
        server_sock = tsocket.from_stdlib_socket(b)
        server_stream = tssl.SSLStream(
            server_sock, SERVER_CTX, server_side=True)
        assert server_stream.server_side

        def client():
            client_ctx = stdlib_ssl.create_default_context(cafile=CA)
            client_sock = client_ctx.wrap_socket(
                a, server_hostname="trio-test-1.example.org")
            client_sock.sendall(b"x")
            assert client_sock.recv(1) == b"y"
            client_sock.sendall(b"z")
            client_sock.unwrap()
        t = threading.Thread(target=client)
        t.start()

        assert await server_stream.recv(1) == b"x"
        await server_stream.sendall(b"y")
        assert await server_stream.recv(1) == b"z"
        assert await server_stream.recv(1) == b""
        await server_stream.graceful_close()

        t.join()


async def test_attributes():
    with ssl_echo_server_raw(expect_fail=True) as sock:
        good_ctx = stdlib_ssl.create_default_context(cafile=CA)
        bad_ctx = stdlib_ssl.create_default_context()
        s = tssl.SSLStream(
            sock, good_ctx, server_hostname="trio-test-1.example.org")

        assert s.wrapped_stream is sock

        # Forwarded attribute getting
        assert s.context is good_ctx
        assert s.server_side == False
        assert s.server_hostname == "trio-test-1.example.org"
        with pytest.raises(AttributeError):
            s.asfdasdfsa

        # __dir__
        assert "wrapped_stream" in dir(s)
        assert "context" in dir(s)

        # Setting the attribute goes through to the underlying object

        # most attributes on SSLObject are read-only
        with pytest.raises(AttributeError):
            s.server_side = True
        with pytest.raises(AttributeError):
            s.server_hostname = "asdf"

        # but .context is *not*. Check that we forward attribute setting by
        # making sure that after we set the bad context our handshake indeed
        # fails:
        s.context = bad_ctx
        assert s.context is bad_ctx
        with pytest.raises(tssl.SSLError):
            await s.do_handshake()


# Note: this test fails horribly if we force TLS 1.2 and trigger a
# renegotiation at the beginning (e.g. by switching to the pyopenssl
# server). Usually the client crashes in SSLObject.write with "UNEXPECTED
# RECORD"; sometimes we get something more exotic like a SyscallError. This is
# odd because openssl isn't doing any syscalls, but so it goes. After lots of
# websearching I'm pretty sure this is due to a bug in OpenSSL, where it just
# can't reliably handle full-duplex communication combined with
# renegotiation. Nice, eh?
#
#   https://rt.openssl.org/Ticket/Display.html?id=3712
#   https://rt.openssl.org/Ticket/Display.html?id=2481
#   http://openssl.6102.n7.nabble.com/TLS-renegotiation-failure-on-receiving-application-data-during-handshake-td48127.html
#   https://stackoverflow.com/questions/18728355/ssl-renegotiation-with-full-duplex-socket-communication
#
# In some variants of this test (maybe only against the java server?) I've
# also seen cases where our sendall blocks waiting to write, and then our recv
# also blocks waiting to write, and they never wake up again. It looks like
# some kind of deadlock. I suspect there may be an issue where we've filled up
# the send buffers, and the remote side is trying to handle the renegotiation
# from inside a write() call, so it has a problem: there's all this application
# data clogging up the pipe, but it can't process and return it to the
# application because it's in write(), and it doesn't want to buffer infinite
# amounts of data, and... actually I guess those are the only two choices.
#
# NSS even documents that you shouldn't try to do a renegotiation except when
# the connection is idle:
#
#   https://developer.mozilla.org/en-US/docs/Mozilla/Projects/NSS/SSL_functions/sslfnc.html#1061582
#
# I begin to see why HTTP/2 forbids renegotiation and TLS 1.3 removes it...

async def test_full_duplex_basics():
    CHUNKS = 100
    CHUNK_SIZE = 65536
    EXPECTED = CHUNKS * CHUNK_SIZE

    sent = bytearray()
    received = bytearray()
    async def sender(s):
        nonlocal sent
        for i in range(CHUNKS):
            print(i)
            chunk = bytes([i] * CHUNK_SIZE)
            sent += chunk
            await s.sendall(chunk)

    async def receiver(s):
        nonlocal received
        while len(received) < EXPECTED:
            chunk = await s.recv(CHUNK_SIZE // 2)
            received += chunk

    with ssl_echo_server() as s:
        async with _core.open_nursery() as nursery:
            nursery.spawn(sender, s)
            nursery.spawn(receiver, s)
            # And let's have some doing handshakes too, everyone
            # simultaneously
            nursery.spawn(s.do_handshake)
            nursery.spawn(s.do_handshake)

        await s.graceful_close()

    assert len(sent) == len(received) == EXPECTED
    assert sent == received


async def test_renegotiation_simple():
    with virtual_ssl_echo_server() as s:
        await s.do_handshake()

        s.wrapped_stream.renegotiate()
        await s.sendall(b"a")
        assert await s.recv(1) == b"a"

        # Have to send some more data back and forth to make sure the
        # renegotiation is finished before shutting down the
        # connection... otherwise openssl raises an error. I think this is a
        # bug in openssl but what can ya do.
        await s.sendall(b"b")
        assert await s.recv(1) == b"b"

        await s.graceful_close()


@slow
async def test_renegotiation_randomized(mock_clock):
    # The only blocking things in this function are our random sleeps, so 0 is
    # a good threshold.
    mock_clock.autojump_threshold = 0

    import random
    r = random.Random(0)

    async def sleeper(_):
        await trio.sleep(r.uniform(0, 10))

    async def clear():
        while s.wrapped_stream.renegotiate_pending():
            with assert_yields():
                await send(b"-")
            with assert_yields():
                await expect(b"-")
        print("-- clear --")

    async def send(byte):
        await s.wrapped_stream.sleeper("outer send")
        print("calling SSLStream.sendall", byte)
        with assert_yields():
            await s.sendall(byte)

    async def expect(expected):
        await s.wrapped_stream.sleeper("expect")
        print("calling SSLStream.recv, expecting", expected)
        assert len(expected) == 1
        with assert_yields():
            assert await s.recv(1) == expected

    with virtual_ssl_echo_server(sleeper=sleeper) as s:
        await s.do_handshake()

        await send(b"a")
        s.wrapped_stream.renegotiate()
        await expect(b"a")

        await clear()

        for i in range(100):
            b1 = bytes([i % 0xff])
            b2 = bytes([(2 * i) % 0xff])
            s.wrapped_stream.renegotiate()
            async with _core.open_nursery() as nursery:
                nursery.spawn(send, b1)
                nursery.spawn(expect, b1)
            async with _core.open_nursery() as nursery:
                nursery.spawn(expect, b2)
                nursery.spawn(send, b2)
            await clear()

        for i in range(100):
            b1 = bytes([i % 0xff])
            b2 = bytes([(2 * i) % 0xff])
            await send(b1)
            s.wrapped_stream.renegotiate()
            await expect(b1)
            async with _core.open_nursery() as nursery:
                nursery.spawn(expect, b2)
                nursery.spawn(send, b2)
            await clear()


    # Checking that wait_sendall_might_not_block and recv don't conflict:

    # 1) Set up a situation where expect (recv) is blocked sending, and
    # wait_sendall_might_not_block comes in.

    # Our recv() call will get stuck when it hits sendall
    async def sleeper_with_slow_sendall(method):
        if method == "sendall":
            await trio.sleep(100000)

    # And our wait_sendall_might_not_block call will give it time to get stuck, and then
    # start
    async def sleep_then_wait_writable():
        await trio.sleep(1000)
        await s.wait_sendall_might_not_block()

    with virtual_ssl_echo_server(sleeper=sleeper_with_slow_sendall) as s:
        await send(b"x")
        s.wrapped_stream.renegotiate()
        async with _core.open_nursery() as nursery:
            nursery.spawn(expect, b"x")
            nursery.spawn(sleep_then_wait_writable)

        await clear()

        await s.graceful_close()

    # 2) Same, but now wait_sendall_might_not_block is stuck when recv tries to send.

    async def sleeper_with_slow_wait_writable_and_expect(method):
        if method == "wait_sendall_might_not_block":
            await trio.sleep(100000)
        elif method == "expect":
            await trio.sleep(1000)

    with virtual_ssl_echo_server(
            sleeper=sleeper_with_slow_wait_writable_and_expect) as s:
        await send(b"x")
        s.wrapped_stream.renegotiate()
        async with _core.open_nursery() as nursery:
            nursery.spawn(expect, b"x")
            nursery.spawn(s.wait_sendall_might_not_block)

        await clear()

        await s.graceful_close()


async def test_resource_busy_errors():
    with ssl_echo_server(expect_fail=True) as s:
        with pytest.raises(RuntimeError) as excinfo:
            async with _core.open_nursery() as nursery:
                nursery.spawn(s.sendall, b"x")
                nursery.spawn(s.sendall, b"x")
        assert "another task" in str(excinfo.value)

        with pytest.raises(RuntimeError) as excinfo:
            async with _core.open_nursery() as nursery:
                nursery.spawn(s.recv, 1)
                nursery.spawn(s.recv, 1)
        assert "another task" in str(excinfo.value)

    a, b = stdlib_socket.socketpair()
    with a, b:
        a.setblocking(False)
        try:
            while True:
                a.send(b"x" * 10000)
        except BlockingIOError:
            pass
        sockstream = tsocket.from_stdlib_socket(a)

        ctx = stdlib_ssl.create_default_context()
        s = tssl.SSLStream(sockstream, ctx, server_hostname="x")

        with pytest.raises(RuntimeError) as excinfo:
            async with _core.open_nursery() as nursery:
                nursery.spawn(s.sendall, b"x")
                nursery.spawn(s.wait_sendall_might_not_block)
        assert "another task" in str(excinfo.value)

        with pytest.raises(RuntimeError) as excinfo:
            async with _core.open_nursery() as nursery:
                nursery.spawn(s.wait_sendall_might_not_block)
                nursery.spawn(s.wait_sendall_might_not_block)
        assert "another task" in str(excinfo.value)


async def test_wait_writable_calls_underlying_wait_writable():
    record = []
    class NotAStream:
        async def wait_sendall_might_not_block(self):
            record.append("ok")
    ctx = stdlib_ssl.create_default_context()
    s = tssl.SSLStream(NotAStream(), ctx, server_hostname="x")
    await s.wait_sendall_might_not_block()
    assert record == ["ok"]


async def test_checkpoints():
    with ssl_echo_server() as s:
        with assert_yields():
            await s.do_handshake()
        with assert_yields():
            await s.do_handshake()
        with assert_yields():
            await s.wait_sendall_might_not_block()
        with assert_yields():
            await s.sendall(b"xxx")
        with assert_yields():
            await s.recv(1)
        # These recv's in theory could return immediately, because the "xxx"
        # was sent in a single record and after the first recv(1) the rest are
        # sitting inside the SSLObject's internal buffers.
        with assert_yields():
            await s.recv(1)
        with assert_yields():
            await s.recv(1)
        with assert_yields():
            await s.unwrap()

    with ssl_echo_server() as s:
        await s.do_handshake()
        with assert_yields():
            await s.graceful_close()


async def test_sendall_empty_string():
    with ssl_echo_server() as s:
        await s.do_handshake()

        # underlying SSLObject interprets writing b"" as indicating an EOF,
        # for some reason. Make sure we don't inherit this.
        with assert_yields():
            await s.sendall(b"")
        with assert_yields():
            await s.sendall(b"")
        await s.sendall(b"x")
        assert await s.recv(1) == b"x"

        await s.graceful_close()


# I'm pretty sure this can't be made to work without better control over the
# flow of data.
#
# async def test_unwrap():
#     client_sock, server_sock = tsocket.socketpair()
#     with client_sock, server_sock:
#         client_ctx = stdlib_ssl.create_default_context(cafile=CA)
#         client_stream = tssl.SSLStream(
#             client_sock, client_ctx, server_hostname="trio-test-1.example.org")
#         server_stream = tssl.SSLStream(
#             server_sock, SERVER_CTX, server_side=True)

#         async def client():
#             await client_stream.do_handshake()
#             await client_stream.sendall(b"x")
#             assert await client_stream.recv(1) == b"y"
#             await client_stream.sendall(b"z")
#             assert await client_stream.recv(1) == b""
#             # Give the server a chance to write trailing data
#             await wait_all_tasks_blocked()
#             raw, trailing = await client_stream.unwrap()
#             assert raw is client_sock
#             assert trailing == b"t"

#         async def server():
#             await server_stream.do_handshake()
#             assert await server_stream.recv(1) == b"x"
#             assert await server_stream.sendall(b"y")
#             assert await server_stream.recv(1) == b"z"
#             # Now client is blocked waiting for us to send something, but
#             # instead we close the TLS connection
#             raw, trailing = await server_stream.unwrap()
#             assert raw is server_sock
#             assert trailing == b""
#             await raw.sendall(b"t")

#         async with _core.open_nursery() as nursery:
#             nursery.spawn(client)
#             nursery.spawn(server)


# maybe a test of presenting a client cert on a renegotiation?

# maybe a test of TLS-over-TLS, just to prove we can?

# unwrap, switching protocols. ...what if we read too much? I guess unwrap
# should also return the residual data from the incoming BIO?

# - sloppy and strict EOF modes

# check getpeercert(), probably need to work around:
# https://bugs.python.org/issue29334

# StapledStream, docs
# testing streams, docs

# repeated calls to close methods are OK

# fix testing.py namespace
