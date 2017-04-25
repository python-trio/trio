import pytest

from pathlib import Path
import threading
import socket as stdlib_socket
import ssl as stdlib_ssl
from contextlib import contextmanager
import subprocess
import shutil
import os

from .. import _core
import trio
from .. import ssl as tssl
from .. import socket as tsocket

from ..testing import assert_yields, wait_all_tasks_blocked


ASSETS_DIR = Path(__file__).parent / "test_ssl_certs"
CA = str(ASSETS_DIR / "trio-test-CA.pem")
CERT1 = str(ASSETS_DIR / "trio-test-1.pem")
CERT2 = str(ASSETS_DIR / "trio-test-2.pem")

class TrickleStream(trio.Stream):
    def __init__(self, wrapped):
        import random
        self._r = random.Random(0)
        self._wrapped = wrapped

    @property
    def can_send_eof(self):
        return self._wrapped.can_send_eof

    def forceful_close(self):
        return self._wrapped.forceful_close()

    async def graceful_close(self):
        return await self._wrapped.graceful_close()

    async def send_eof(self):
        return await self._wrapped.send_eof()

    async def wait_writable(self):
        return await self._wrapped.wait_writable()

    # The actual work is here:

    async def sendall(self, data):
        for i in range(len(data)):
            await self._wrapped.sendall(data[i:i+1])
            await trio.sleep(self._r.uniform(0, 1))

    async def recv(self, max_bytes):
        await trio.sleep(self._r.uniform(0, 1))
        return await self._wrapped.recv(1)


def ssl_echo_serve_sync(sock, *, expect_fail=False):
    try:
        server_ctx = stdlib_ssl.create_default_context(
            stdlib_ssl.Purpose.CLIENT_AUTH,
        )
        server_ctx.load_cert_chain(CERT1)
        wrapped = server_ctx.wrap_socket(sock, server_side=True)
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


# fixture that gives a raw socket connected to a trio-test-1 echo server
# (running in a thread)
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


# fixture that gives a properly set up SSLStream connected to a trio-test-1
# echo server (running in a thread)
@contextmanager
def ssl_echo_server(**kwargs):
    with ssl_echo_server_raw(**kwargs) as sock:
        #sock = TrickleStream(sock)
        client_ctx = stdlib_ssl.create_default_context(cafile=CA)
        yield tssl.SSLStream(
            sock, client_ctx, server_hostname="trio-test-1.example.org")


from OpenSSL import SSL
class PyOpenSSLEchoStream(trio.Stream):
    def __init__(self):
        ctx = SSL.Context(SSL.TLSv1_2_METHOD)
        ctx.use_certificate_file(CERT1)
        ctx.use_privatekey_file(CERT1)
        self._conn = SSL.Connection(ctx, None)
        self._conn.set_accept_state()
        self._lot = _core.ParkingLot()
        self._pending_cleartext = bytearray()

    can_send_eof = False
    async def send_eof(self):
        raise RuntimeError

    def forceful_close(self):
        self._conn.bio_shutdown()

    async def graceful_close(self):
        self.forceful_close()

    async def wait_writable(self):
        pass

    def renegotiate_pending(self):
        return self._conn.renegotiate_pending()

    def renegotiate(self):
        # Returns false if a renegotation is already in progress, meaning
        # nothing happens.
        assert self._conn.renegotiate()

    async def sendall(self, data):
        await _core.yield_briefly()
        self._conn.bio_write(data)
        while True:
            try:
                data = self._conn.recv(1)
            except SSL.ZeroReturnError:
                self._conn.shutdown()
                print("R:", self._conn.total_renegotiations())
                break
            except SSL.WantReadError:
                break
            else:
                # if data == b"\xff":
                #     self._conn.renegotiate()
                #self._conn.send(data)
                self._pending_cleartext += data
        self._lot.unpark_all()

    async def recv(self, nbytes):
        #await _core.yield_briefly()
        while True:
            try:
                return self._conn.bio_read(nbytes)
            except SSL.WantReadError:
                # No data in our ciphertext buffer; try to generate some.
                if self._pending_cleartext:
                    # We have some cleartext; maybe we can encrypt it and then
                    # return it.
                    print("trying", self._pending_cleartext)
                    try:
                        # PyOpenSSL bug: doesn't accept bytearray
                        # https://github.com/pyca/pyopenssl/issues/621
                        self._conn.send(bytes(self._pending_cleartext))
                    except SSL.WantReadError:
                        # We didn't manage to send the cleartext (and in
                        # particular we better leave it there to try
                        # again, due to openssl's retry semantics), but
                        # it's possible we pushed a renegotiation forward
                        # and *now* we have data to send.
                        try:
                            return self._conn.bio_read(nbytes)
                        except SSL.WantReadError:
                            # Nope. We're just going to have to wait for
                            # someone to call sendall() to give use more
                            # data.
                            print("parking (a)")
                            await self._lot.park()
                    else:
                        # We successfully sent this cleartext, so we don't
                        # have to again.
                        del self._pending_cleartext[:]
                else:
                    # no pending cleartext; nothing to do but wait for someone
                    # to call sendall
                    print("parking (b)")
                    await self._lot.park()


# experiment with using PyOpenSSL
def ssl_echo_serve_sync_pyopenssl(sock, *, expect_fail=False):
    # ref:
    # https://github.com/pyca/pyopenssl/blob/master/examples/simple/server.py
    # https://github.com/pyca/pyopenssl/blob/master/examples/simple/client.py
    from OpenSSL import SSL
    try:
        # Hard-code a version that supports renegotiation (since in the future
        # 1.3 won't)
        ctx = SSL.Context(SSL.TLSv1_2_METHOD)
        ctx.use_certificate_file(CERT1)
        ctx.use_privatekey_file(CERT1)
        wrapped = SSL.Connection(ctx, sock)
        wrapped.set_accept_state()
        wrapped.do_handshake()
        while True:
            try:
                data = wrapped.recv(1)
            except SSL.ZeroReturnError:
                wrapped.shutdown()
                return
            except SSL.WantReadError:
                # This sometimes happens during renegotiation, even on
                # blocking sockets.
                # See: https://github.com/pyca/pyopenssl/issues/190
                continue
            if data == b"\xff":
                if not wrapped.renegotiate_pending():
                    # Request that the next IO trigger the start of a
                    # renegotiation
                    print("starting renegotiation")
                    assert wrapped.renegotiate()
                else:
                    print("not starting renegotiation b/c last is still going")
            wrapped.send(data)
    except Exception as exc:
        if expect_fail:
            print("ssl_echo_serve_sync got error as expected:", repr(exc))
        else:
            raise
    else:
        if expect_fail:
            print("failed to fail?!")


@contextmanager
def ssl_echo_server_pyopenssl(**kwargs):
    a, b = stdlib_socket.socketpair()
    with a, b:
        t = threading.Thread(
            target=ssl_echo_serve_sync_pyopenssl,
            args=(b,),
            kwargs=kwargs,
        )
        t.start()

        client_ctx = stdlib_ssl.create_default_context(cafile=CA)
        tsock = tsocket.from_stdlib_socket(a)
        #tsock = TrickleStream(tsock)
        yield tssl.SSLStream(
            tsock, client_ctx, server_hostname="trio-test-1.example.org")

    # exiting the context manager closes the sockets, which should force the
    # thread to shut down (possibly with an error)
    t.join()


@contextmanager
def ssl_echo_server_pyopenssl(**kwargs):
    client_ctx = tssl.create_default_context(cafile=CA)
    fakesock = PyOpenSSLEchoStream()
    yield tssl.SSLStream(
        fakesock, client_ctx, server_hostname="trio-test-1.example.org")


needs_java = pytest.mark.skipif(shutil.which("java") is None, reason="need java")

@contextmanager
def ssl_echo_server_java(**kwargs):
    p = subprocess.Popen(
        ["java", "SSLEchoServer", CERT1.replace("pem", "pkcs12")],
        stdout=subprocess.PIPE,
        universal_newlines=True,
        env={**os.environ, "CLASSPATH": str(ASSETS_DIR)},
    )
    try:
        port = int(p.stdout.readline())

        with stdlib_socket.create_connection(("127.0.0.1", port)) as ssock:
            tsock = tsocket.from_stdlib_socket(ssock)
            client_ctx = tssl.create_default_context(cafile=CA)
            yield tssl.SSLStream(
                tsock, client_ctx, server_hostname="trio-test-1.example.org")
    finally:
        p.kill()
        p.wait()


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
        server_ctx = tssl.create_default_context(tssl.Purpose.CLIENT_AUTH)
        server_ctx.load_cert_chain(CERT2)
        server_stream = tssl.SSLStream(
            server_sock, server_ctx, server_side=True)
        assert server_stream.server_side

        def client():
            client_ctx = stdlib_ssl.create_default_context(cafile=CA)
            client_sock = client_ctx.wrap_socket(
                a, server_hostname="trio-test-2.example.org")
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


async def test_send_eof():
    with ssl_echo_server(expect_fail=True) as s:
        assert not s.can_send_eof
        await s.do_handshake()
        with pytest.raises(RuntimeError):
            await s.send_eof()
        await s.graceful_close()


# Note: this test fails horribly if we force TLS 1.2 and trigger a
# renegotiation at the beginning (e.g. by switching to the pyopenssl server
# and sending a b"\xff" as the first byte). Usually the client crashes in
# SSLObject.write with "UNEXPECTED RECORD"; sometimes we get something more
# exotic like a SyscallError. This is odd because openssl isn't doing any
# syscalls, but so it goes. After lots of websearching I'm pretty sure this is
# due to a bug in OpenSSL, where it just can't reliably handle full-duplex
# communication combined with renegotiation. Nice, eh?
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


@needs_java
async def test_renegotiation():
    with ssl_echo_server_pyopenssl() as s:
        print("-- 1")
        await s.sendall(b"a")
        print("-- 2")
        assert await s.recv(1) == b"a"
        print("-- 3")
        await s.sendall(b"\xff")
        print("-- 4")
        assert await s.recv(1) == b"\xff"
        print("-- 5")
        await s.sendall(b"a")
        print("-- 6")
        assert await s.recv(1) == b"a"

        async def send_a():
            print("send_a")
            await s.sendall(b"a")

        async def recv_ff():
            print("recv_ff")
            assert await s.recv(1) == b"\xff"

        print("-- 7")
        await s.sendall(b"\xff")
        print("-- 8")
        async with _core.open_nursery() as nursery:
            nursery.spawn(send_a)
            #await _core.wait_all_tasks_blocked()
            nursery.spawn(recv_ff)
        print("-- 9")
        assert await s.recv(1) == b"a"

        print("-- 7.2")
        await s.sendall(b"\xff")
        print("-- 8.2")
        async with _core.open_nursery() as nursery:
            nursery.spawn(recv_ff)
            await _core.wait_all_tasks_blocked()
            nursery.spawn(send_a)
        print("-- 9.2")
        assert await s.recv(1) == b"a"

        print("-- 10")
        await s.sendall(b"b")
        print("-- 11")
        assert await s.recv(1) == b"b"

        print("-- 12")
        async def send_ff():
            print("send_ff")
            await s.sendall(b"\xff")

        for _ in range(10):
            async with _core.open_nursery() as nursery:
                nursery.spawn(send_ff)
                nursery.spawn(recv_ff)
            # freezes without this? I guess something bad about starting a new
            # renegotiation while the last one is still going...
            await s.sendall(b"a")
            assert await s.recv(1) == b"a"

        print("-- 13")
        async def send_lots_of_ffa(count):
            print("send_lots_of_ffa")
            await s.sendall(b"\xffa" * count)

        async def recv_lots_of_ffa(count):
            expected = b"\xffa" * count
            got = bytearray()
            while len(got) < len(expected):
                got += await s.recv(1)
            assert got == expected

        async with _core.open_nursery() as nursery:
            nursery.spawn(send_lots_of_ffa, 10)
            nursery.spawn(recv_lots_of_ffa, 10)

        print("--")
        await s.sendall(b"b")
        assert await s.recv(1) == b"b"

        print("closing")
        await s.graceful_close()


@needs_java
async def test_renegotiation():
    with ssl_echo_server_pyopenssl() as s:
        await s.do_handshake()

        async def expect(expected):
            assert len(expected) == 1
            assert await s.recv(1) == expected

        # Send some data back and forth to make sure any previous
        # renegotations have finished
        async def clear():
            while s.wrapped_stream.renegotiate_pending():
                await s.sendall(b"-")
                await expect(b"-")
            print("--")

        # simplest cases
        await s.sendall(b"a")
        await expect(b"a")

        await clear()

        s.wrapped_stream.renegotiate()
        await s.sendall(b"b")
        await expect(b"b")

        await clear()

        await s.sendall(b"c")
        s.wrapped_stream.renegotiate()
        await expect(b"c")

        await clear()

        # This renegotiate starts with the sendall(x), then the simultaneous
        # sendall(y) and recv(x) end up both wanting to send, and the recv(x)
        # has to wait; this wouldn't work if we didn't have a lock protecting
        # wrapped_stream.sendall.
        s.wrapped_stream.renegotiate()
        await s.sendall(b"x")
        async with _core.open_nursery() as nursery:
            nursery.spawn(s.sendall, b"y")
            nursery.spawn(expect, b"x")
        await expect(b"y")

        await clear()

        s.wrapped_stream.renegotiate()
        async with _core.open_nursery() as nursery:
            nursery.spawn(expect, b"x")
            await _core.wait_all_tasks_blocked()
            nursery.spawn(s.sendall, b"x")

        await clear()

        for _ in range(10):
            s.wrapped_stream.renegotiate()
            async with _core.open_nursery() as nursery:
                nursery.spawn(s.sendall, b"a")
                nursery.spawn(expect, b"a")
            # freezes without this? I guess something bad about starting a new
            # renegotiation while the last one is still going...
            await s.sendall(b"z")
            await expect(b"z")

        # Have to make sure the last renegotiation has had a chance to fully
        # finish before shutting down; openssl errors out if we try to call
        # SSL_shutdown while a renegotiation is in progress. (I think this is
        # a bug, but not much we can do about it...)
        await clear()

        await s.graceful_close()

# assert checkpoints

# - simultaneous read and read, or write and write -> error

# check wait_writable (and write + wait_writable should also error)

# unwrap, switching protocols. ...what if we read too much? I guess unwrap
# should also return the residual data from the incoming BIO?

# - sloppy and strict EOF modes

# maybe some tests with a stream that writes and receives in small pieces, so
# there's lots of looping and retrying?

# check getpeercert(), probably need to work around:
# https://bugs.python.org/issue29334

# clean things up:
# - I think we can delete java and pkcs12 and even trio-example-2
