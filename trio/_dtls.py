# https://datatracker.ietf.org/doc/html/rfc6347

# XX: figure out what to do about the pyopenssl dependency
# Maybe the toplevel __init__.py should use __getattr__ trickery to load all
# the DTLS code lazily?

import struct
import hmac
import os
import io
import enum
from itertools import count
import weakref

import attr
from OpenSSL import SSL

import trio
from trio._util import NoPublicConstructor

MAX_UDP_PACKET_SIZE = 65527

# There are a bunch of different RFCs that define these codes, so for a
# comprehensive collection look here:
# https://www.iana.org/assignments/tls-parameters/tls-parameters.xhtml
class ContentType(enum.IntEnum):
    change_cipher_spec = 20
    alert = 21
    handshake = 22
    application_data = 23
    heartbeat = 24


class HandshakeType(enum.IntEnum):
    hello_request = 0
    client_hello = 1
    server_hello = 2
    hello_verify_request = 3
    new_session_ticket = 4
    end_of_early_data = 4
    encrypted_extensions = 8
    certificate = 11
    server_key_exchange = 12
    certificate_request = 13
    server_hello_done = 14
    certificate_verify = 15
    client_key_exchange = 16
    finished = 20
    certificate_url = 21
    certificate_status = 22
    supplemental_data = 23
    key_update = 24
    compressed_certificate = 25
    ekt_key = 26
    message_hash = 254


class ProtocolVersion:
    DTLS10 = bytes([254, 255])
    DTLS12 = bytes([254, 253])


EPOCH_MASK = 0xffff << (6 * 8)


# Conventions:
# - All functions that handle network data end in _untrusted.
# - All functions end in _untrusted MUST make sure that bad data from the
#   network cannot *only* cause BadPacket to be raised. No IndexError or
#   struct.error or whatever.
class BadPacket(Exception):
    pass


# This checks that the DTLS 'epoch' field is 0, which is true iff we're in the
# initial handshake. It doesn't check the ContentType, because not all
# handshake messages have ContentType==handshake -- for example,
# ChangeCipherSpec is used during the handshake but has its own ContentType.
#
# Cannot fail.
def part_of_handshake_untrusted(packet):
    # If the packet is too short, then slicing will successfully return a
    # short string, which will necessarily fail to match.
    return packet[3:5] == b"\x00\x00"


# Cannot fail
def is_client_hello_untrusted(packet):
    try:
        return (
            packet[0] == ContentType.handshake
            and packet[13] == HandshakeType.client_hello
        )
    except IndexError:
        # Invalid DTLS record
        return False


# DTLS records are:
# - 1 byte content type
# - 2 bytes version
# - 8 bytes epoch+seqno
#    Technically this is 2 bytes epoch then 6 bytes seqno, but we treat it as
#    a single 8-byte integer, where epoch changes are represented as jumping
#    forward by 2**(6*8).
# - 2 bytes payload length (unsigned big-endian)
# - payload
RECORD_HEADER = struct.Struct("!B2sQH")


@attr.frozen
class Record:
    content_type: int
    version: bytes
    epoch_seqno: int
    payload: bytes


def records_untrusted(packet):
    i = 0
    while i < len(packet):
        try:
            ct, version, epoch_seqno, payload_len = RECORD_HEADER.unpack_from(packet, i)
        except struct.error as exc:
            raise BadPacket("invalid record header") from exc
        i += RECORD_HEADER.size
        payload = packet[i : i + payload_len]
        if len(payload) != payload_len:
            raise BadPacket("short record")
        i += payload_len
        yield Record(ct, version, epoch_seqno, payload)


def encode_record(record):
    header = RECORD_HEADER.pack(
        record.content_type,
        record.version,
        record.epoch_seqno,
        len(record.payload),
    )
    return header + record.payload


# Handshake messages are:
# - 1 byte message type
# - 3 bytes total message length
# - 2 bytes message sequence number
# - 3 bytes fragment offset
# - 3 bytes fragment length
HANDSHAKE_MESSAGE_HEADER = struct.Struct("!B3sH3s3s")


@attr.frozen
class HandshakeFragment:
    msg_type: int
    msg_len: int,
    msg_seq: int
    frag_offset: int
    frag_len: int
    frag: bytes


def decode_handshake_fragment_untrusted(payload):
    # Raises BadPacket if decoding fails
    try:
        (
            msg_type,
            msg_len_bytes,
            msg_seq,
            frag_offset_bytes,
            frag_len_bytes,
        ) = HANDSHAKE_MESSAGE_HEADER.unpack_from(payload)
    except struct.error as exc:
        raise BadPacket("bad handshake message header") from exc
    # 'struct' doesn't have built-in support for 24-bit integers, so we
    # have to do it by hand. These can't fail.
    msg_len = int.from_bytes(msg_len_bytes, "big")
    frag_offset = int.from_bytes(frag_offset_bytes, "big")
    frag_len = int.from_bytes(frag_len_bytes, "big")
    frag = payload[HANDSHAKE_MESSAGE_HEADER.size:]
    if len(frag) != frag_len:
        raise BadPacket("short fragment")
    return HandshakeFragment(
        msg_type,
        msg_len,
        msg_seq,
        frag_offset,
        frag_len,
        frag,
    )


def encode_handshake_fragment(hsf):
    hs_header = HANDSHAKE_MESSAGE_HEADER.pack(
        hsf.msg_type,
        hsf.msg_len.to_bytes(3, "big"),
        hsf.msg_seq,
        hsf.frag_offset.to_bytes(3, "big"),
        hsf.frag_len.to_bytes(3, "big"),
    )
    return hs_header + hsf.body


def decode_client_hello_untrusted(packet):
    # Raises BadPacket if parsing fails
    # Returns (record epoch_seqno, cookie from the packet, data that should be
    # hashed into cookie)
    try:
        # ClientHello has to be the first record in the packet
        record = next(records_untrusted(packet))
        if record.content_type != ContentType.handshake:
            raise BadPacket("not a handshake record")
        fragment = decode_handshake_fragment_untrusted(record.payload)
        if fragment.msg_type != HandshakeType.client_hello:
            raise BadPacket("not a ClientHello")
        # ClientHello can't be fragmented, because reassembly requires holding
        # per-connection state, and we refuse to allocate per-connection state
        # until after we get a valid ClientHello.
        if fragment.frag_offset != 0:
            raise BadPacket("fragmented ClientHello")
        if fragment.frag_len != fragment.msg_len:
            raise BadPacket("fragmented ClientHello")

        # As per RFC 6347:
        #
        #   When responding to a HelloVerifyRequest, the client MUST use the
        #   same parameter values (version, random, session_id, cipher_suites,
        #   compression_method) as it did in the original ClientHello.  The
        #   server SHOULD use those values to generate its cookie and verify that
        #   they are correct upon cookie receipt.
        #
        # However, the record-layer framing can and will change (e.g. the
        # second ClientHello will have a new record-layer sequence number). So
        # we need to pull out the handshake message alone, discarding the
        # record-layer stuff, and then we're going to hash all of it *except*
        # the cookie.

        body = fragment.frag
        # ClientHello is:
        #
        # - 2 bytes client_version
        # - 32 bytes random
        # - 1 byte session_id length
        # - session_id
        # - 1 byte cookie length
        # - cookie
        # - everything else
        #
        # So to find the cookie, so we need to figure out how long the
        # session_id is and skip past it.
        session_id_len = body[2 + 32]
        cookie_len_offset = 2 + 32 + 1 + session_id_len
        cookie_len = body[cookie_len_offset]

        cookie_start = cookie_len_offset + 1
        cookie_end = cookie_start + cookie_len

        before_cookie = body[:cookie_start]
        cookie = body[cookie_start:cookie_end]
        after_cookie = body[cookie_end:]

        if len(cookie) != cookie_len:
            raise BadPacket("short cookie")
        return (record.epoch_seqno, cookie, before_cookie + after_cookie)

    except (struct.error, IndexError) as exc:
        raise BadPacket("bad ClientHello") from exc


@attr.frozen
class HandshakeMessage:
    record_version: bytes
    msg_type: HandshakeType
    msg_seq: int
    body: bytearray


# ChangeCipherSpec is part of the handshake, but it's not a "handshake
# message" and can't be fragmented the same way. Sigh.
@attr.frozen
class PseudoHandshakeMessage:
    record_version: bytes
    content_type: int
    payload: bytes


# This takes a raw outgoing handshake volley that openssl generated, and
# reconstructs the handshake messages inside it, so that we can repack them
# into records while retransmitting. So the data ought to be well-behaved --
# it's not coming from the network.
def decode_volley_trusted(volley):
    messages = []
    messages_by_seq = {}
    for record in records_untrusted(volley):
        if record.content_type == ContentType.change_cipher_spec:
            messages.append(PseudoHandshakeMessage(record.version,
                                                   record.content_type, record.payload))
        else:
            assert record.content_type == ContentType.handshake
            fragment = decode_handshake_fragment_untrusted(record.payload)
            msg_type = HandshakeType(fragment.msg_type)
            if fragment.msg_seq not in messages_by_seq:
                msg = HandshakeMessage(
                    record.version, msg_type, fragment.msg_seq, bytearray(fragment.msg_len)
                )
                messages.append(msg)
                messages_by_seq[fragment.msg_seq] = msg
            else:
                msg = messages_by_seq[msg_seq]
            assert msg.msg_type == fragment.msg_type
            assert msg.msg_seq == fragment.msg_seq
            assert len(msg.body) == fragment.msg_len

            msg.body[fragment.frag_offset : fragment.frag_offset + fragment.frag_len] = fragment.frag

    return messages


class RecordEncoder:
    def __init__(self, first_record_seq):
        self._record_seq = count(first_record_seq)

    def skip_first_record_number(self):
        assert next(self._record_seq) == 0

    def encode_volley(self, messages, mtu):
        packets = []
        packet = bytearray()
        for message in messages:
            if isinstance(message, PseudoHandshakeMessage):
                space = mtu - len(packet) - RECORD_HEADER.size - len(message.payload)
                if space <= 0:
                    packets.append(packet)
                    packet = bytearray()
                packet += RECORD_HEADER.pack(
                    message.content_type,
                    message.record_version,
                    next(self._record_seq),
                    len(message.payload),
                )
                packet += payload
                assert len(packet) <= mtu
            else:
                msg_len_bytes = message.msg_len.to_bytes(3, "big")
                frag_offset = 0
                while frag_offset < len(message.body):
                    space = mtu - len(packet) - RECORD_HEADER.size - HANDSHAKE_MESSAGE_HEADER.size
                    if space <= 0:
                        packets.append(packet)
                        packet = bytearray()
                        continue
                    frag = message.body[frag_offset:frag_offset + space]
                    frag_offset_bytes = frag_offset.to_bytes(3, "big")
                    frag_len_bytes = len(frag).to_bytes(3, "big")

                    packet += RECORD_HEADER.pack(
                        ContentType.handshake,
                        message.record_version,
                        next(self._record_seq),
                        HANDSHAKE_MESSAGE_HEADER.size + len(frag),
                    )

                    packet += HANDSHAKE_MESSAGE_HEADER.pack(
                        message.msg_type,
                        msg_len_bytes,
                        message.msg_seq,
                        frag_offset_bytes,
                        frag_len_bytes,
                    )

                    packet += frag

                    assert len(packet) <= mtu

        if packet:
            packets.append(packet)

        return packets


# This bit requires implementing a bona fide cryptographic protocol, so even though it's
# a simple one let's take a moment to discuss the design.
#
# Our goal is to force new incoming handshakes that claim to be coming from a
# given ip:port to prove that they can also receive packets sent to that
# ip:port. (There's nothing in UDP to stop someone from forging the return
# address, and it's often used for stuff like DoS reflection attacks, where
# an attacker tries to trick us into sending data at some innocent victim.)
# For more details, see:
#
#    https://datatracker.ietf.org/doc/html/rfc6347#section-4.2.1
#
# To do this, when we receive an initial ClientHello, we calculate a magic
# cookie, and send it back as a HelloVerifyRequest. Then the client sends us a
# second ClientHello, this time with the magic cookie included, and after we
# check that this cookie is valid we go ahead and start the handshake proper.
#
# So the magic cookie needs the following properties:
# - No-one can forge it without knowing our secret key
# - It ensures that the ip, port, and ClientHello contents from the response
#   match those in the challenge
# - It expires after a short-ish period (so that if an attacker manages to steal one, it
#   won't be useful for long)
# - It doesn't require storing any peer-specific state on our side
#
# To do that, we take the ip/port/ClientHello data and compute an HMAC of them, using a
# secret key we generate on startup. We also include:
#
# - The current time (using Trio's clock), rounded to the nearest 30 seconds
# - A random salt
#
# Then the cookie the salt + the HMAC digest.
#
# When verifying a cookie, we use the salt + new ip/port/ClientHello data to recompute
# the HMAC digest, for both the current time and the current time minus 30 seconds, and
# if either of them match, we consider the cookie good.
#
# Including the rounded-off time like this means that each cookie is good for at least
# 30 seconds, and possibly as much as 60 seconds.
#
# The salt is probably not necessary -- I'm pretty sure that all it does is make it hard
# for an attacker to figure out when our clock ticks over a 30 second boundary. Which is
# probably pretty harmless? But it's easier to add the salt than to convince myself that
# it's *completely* harmless, so, salt it is.

COOKIE_REFRESH_INTERVAL = 30  # seconds
KEY = None
KEY_BYTES = 8
COOKIE_HASH = "sha256"
SALT_BYTES = 8


def _current_cookie_tick():
    return int(trio.current_time() / COOKIE_REFRESH_INTERVAL)


# Simple deterministic, bijective serializer -- i.e., a useful tool for hashing
# structured data.
def _signable(*fields):
    out = []
    for field in fields:
        out.append(struct.encode("!Q", len(field)))
        out.append(field)
    return b"".join(out)


def _make_cookie(salt, tick, address, client_hello_bits):
    assert len(salt) == SALT_BYTES

    global KEY
    if KEY is None:
        KEY = os.urandom(KEY_BYTES)

    signable_data = _signable(
        salt,
        struct.encode("!Q", tick),
        # address is a mix of strings and ints, and variable length, so pack
        # it into a single nested field
        _signable(*(str(part).encode() for part in address)),
        client_hello_bits,
    )

    return salt + hmac.digest(KEY, signable_data, COOKIE_HASH)


def valid_cookie(cookie, address, client_hello_bits):
    if len(cookie) > SALT_BYTES:
        salt = cookie[:SALT_BYTES]

        cur_cookie = _make_cookie(salt, tick, address, client_hello_bits)
        old_cookie = _make_cookie(salt, tick - 1, address, client_hello_bits)

        return (
            hmac.compare_digest(cookie, cur_cookie)
            | hmac.compare_digest(cookie, old_cookie)
        )
    else:
        return False


def challenge_for(address, epoch_seqno, client_hello_bits):
    salt = os.urandom(SALT_BYTES)
    tick = _current_cookie_tick()
    cookie = _make_cookie(salt, tick, address, client_hello_bits)

    # HelloVerifyRequest body is:
    # - 2 bytes version
    # - length-prefixed cookie
    #
    # The DTLS 1.2 spec says that for this message specifically we should use
    # the DTLS 1.0 version.
    #
    # (It also says the opposite of that, but that part is a mistake:
    #    https://www.rfc-editor.org/errata/eid4103
    # ).
    #
    # And I guess we use this for both the message-level and record-level
    # ProtocolVersions, since we haven't negotiated anything else yet?
    body = ProtocolVersion.DTLS10 + bytes([len(cookie)]) + cookie

    # RFC says have to copy the client's record number
    # Errata says it should be handshake message number
    # Openssl copies back record sequence number, and always sets message seq
    # number 0. So I guess we'll follow openssl.
    hs = HandshakeFragment(
        msg_type=HandshakeType.hello_verify_request,
        msg_len=len(body),
        msg_seq=0,
        frag_offset=0,
        frag_len=len(body),
        frag_bytes=body,
    )
    payload = encode_handshake_fragment(hs)

    packet = encode_record(Record(ContentType.handshake,
                                  ProtocolVersion.DTLS10, epoch_seqno, payload))
    return packet


# when listening, definitely needs background tasks to handle reading+handshaking
# connect() (add_peer()?) should probably handle handshake directly
# in *theory* if only had client-mode, then could have multiple tasks calling
# add_peer() simultaneously +
#
# alternatively: add_peer/listen as sync functions to express intentions, plus
# user is expected to regularly be pumping the receive loop. Handshakes don't
# progress unless you're doing this. Each packet receive call runs through the
# whole DTLS state machine.
#
# Problem: in this model, handshake timeouts are a pain in the butt. (Need to
# track them in some kind of manual timer wheel etc.). We don't
# want to write an explicit state machine; we want to take advantage of trio's
# tools.
#
# Therefore, handshakes should have a host task.
#
# And if handshakes have a host task, then what?
#
# main thing with handshakes is that might want to read packets to handle them
# even if user isn't otherwise reading packets. Our two options are to either
# have handshakes running continuously and potentially drop data packets
# internally, or else to only process handshakes while the user is asking for
# data.
#
# I guess dropping is better? We can have an internal queue size + stats on
# what's dropped?
#
# and if we're going to do our own dropping, then it's ok to have a constant
# reader task running...

# One option would be to have a fully connection-based API. Make a DTLS socket
# endpoint, and then call `await connect(...)` to get a DTLS socket
# connection, or `serve(task_fn)` so `task_fn` runs on each incoming
# handshake. Lifetimes are then clear. (GC shutdown still a bit of a pain, but
# whatever, can handle it.)
#
# Alternatively, lean into the single socket API. Handshakes happen in
# background, peers are identified by magic tokens returned from 'connect' or
# 'receive'. Need some synthetic event for "new client connected" to avoid the
# possibility of clients filling up connection table with immortal nonsense.
# Need way to forget specific peers.
#
# In both cases: what to do when in server mode, and a new connection
# *replaces* an existing connection? (or in mixed client/server mode
# similarly, I guess?) I guess for single-socket API you need a way to get
# these notifications anyway... for server mode maybe the old one gets marked
# closed and a new one is created? so need some way to signal EOF, which isn't
# a thing otherwise. (BrokenResourceError?)
#
# Also for future-DTLS (and QUIC etc.) there's connection migration, where the
# peer address changes. I guess the user doesn't necessarily care about
# getting notifications of this, as long as their connection remains bound to
# the right peer? It does rule out the use of connected UDP sockets though.


class _Queue:
    def __init__(self, incoming_packets_buffer):
        self._s, self._r = trio.open_memory_channel(incoming_packets_buffer)

    async def put(self, obj):
        await self._s.send(obj)

    async def get(self):
        return self._r.receive()


def _read_loop(read_fn):
    chunks = []
    while True:
        try:
            chunk = read_fn(2 ** 14)  # max TLS record size
        except SSL.WantReadError:
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


async def handle_client_hello_untrusted(dtls, address, packet):
    if dtls._listening_context is None:
        return

    try:
        epoch_seqno, cookie, bits = decode_client_hello_untrusted(address, packet)
    except BadPacket:
        return

    if not valid_cookie(cookie, address, bits):
        challenge_packet = challenge_for(address, epoch_seqno, bits)
        try:
            await dtls.sock.sendto(address, challenge_packet)
        except OSError:
            pass
    else:
        stream = DTLSStream(dtls, address, dtls._listening_context)
        stream._inject_client_hello(packet)
        old_stream = dlts._streams.get(address)
        if old_stream is not None:
            old_stream._break(RuntimeError("peer started a new DTLS connection"))
        dtls._streams[address] = stream
        dtls._incoming_connections_q.put_nowait(stream)


async def dtls_receive_loop(dtls):
    sock = dtls.socket
    dtls_ref = weakref.weakref(dtls)
    del dtls
    while True:
        try:
            address, packet = await sock.recvfrom()
        except ClosedResourceError:
            return
        except OSError as exc:
            dtls = dtls_ref()
            if dtls is None:
                return
            dtls._break(exc)
            return
        # All of the following is sync, so we can be confident that our
        # reference to dtls remains valid.
        dtls = dtls_ref()
        try:
            if dtls is None:
                return
            if is_client_hello_untrusted(packet):
                await handle_client_hello_untrusted(dtls, address, packet)
            elif address in dtls._streams:
                stream = dtls._streams[address]
                if stream._did_handshake and part_of_handshake_untrusted(packet):
                    # The peer just sent us more handshake messages, that aren't a
                    # ClientHello, and we thought the handshake was done. Some of the
                    # packets that we sent to finish the handshake must have gotten
                    # lost. So re-send them. We do this directly here instead of just
                    # putting it into the queue, because there's no guarantee that
                    # anyone is reading from the queue, because we think the handshake
                    # is done!
                    await stream._resend_final_volley()
                else:
                    try:
                        stream._q.put_nowait(packet)
                    except trio.WouldBlock:
                        stream.packets_dropped_in_trio += 1
            else:
                # Drop packet
                pass
        finally:
            del dtls


class DTLSStream(trio.abc.Channel[bytes], metaclass=NoPublicConstructor):
    def __init__(self, dtls, peer_address, ctx):
        self.dtls = dtls
        self.peer_address = peer_address
        self.packets_dropped_in_trio = 0
        self._mtu = 1472  # XX
        self._did_handshake = False
        self._ssl = SSL.Connection(ctx)
        self._broken = False
        self._closed = False
        self._q = Queue(dtls.incoming_packets_buffer)
        self._handshake_lock = trio.Lock()
        self._record_encoder = RecordEncoder()

    def _break(self, reason: BaseException):
        self._broken = True
        self._broken_reason = reason
        # XX wake things up

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.dtls._streams.get(self.peer_address) is self:
            del self.dtls._streams[self.peer_address]
        # Will wake any tasks waiting on self._q.get with a
        # ClosedResourceError
        self._q._r.close()

    async def aclose(self):
        self.close()
        await trio.lowlevel.checkpoint()

    def _inject_client_hello(self, packet):
        stream._ssl.bio_write(packet)
        # If we're on the server side, then we already sent record 0 as our cookie
        # challenge. So we want to start the handshake proper with record 1.
        self._record_encoder.skip_first_record_number()

    async def _send_volley(self, volley_messages):
        packets = self._record_encoder(volley_messages, self._mtu)
        for packet in packets:
            await self.dtls.socket.sendto(self.peer_address, packet)

    async def _resend_final_volley(self):
        await self._send_volley(self._final_volley)

    async def do_handshake(self):
        async with self._handshake_lock:
            if self._did_handshake:
                return
            # If we're a client, we send the initial volley. If we're a server, then
            # the initial ClientHello has already been inserted into self._ssl's
            # read BIO. So either way, we start by generating a new volley.
            try:
                self._ssl.do_handshake()
            except SSL.WantReadError:
                pass

            volley_messages = []
            def read_volley():
                volley_bytes = read_loop(self._ssl.bio_read)
                new_volley_messages = decode_volley_trusted(volley_bytes)
                if (
                    new_volley_messages and volley_messages and
                    new_volley_messages[0].msg_seq == volley_messages[0].msg_seq
                ):
                    # openssl decided to retransmit; discard because we'll handle this
                    # ourselves
                    return []
                else:
                    return new_volley_messages

            volley_messages = read_volley()
            # If we don't have messages to send in our initial volley, then something
            # has gone very wrong. (I'm not sure this can actually happen without an
            # error from OpenSSL, but let's cover our bases.)
            if not volley_messages:
                self._break(SSL.Error("something wrong with peer's ClientHello"))
                # XX raise
                return

            while True:
                assert volley_messages
                await self._send_volley(volley_messages)
                with trio.move_on_after(1) as cscope:
                    async for packet in self._q._r:
                        self._ssl.bio_write(packet)
                        try:
                            self._ssl.do_handshake()
                        except SSL.WantReadError:
                            pass
                        else:
                            # No exception -> the handshake is done, and we can
                            # switch into data transfer mode.
                            self._did_handshake = True
                            # Might be empty, but that's ok
                            self._final_volley = read_volley()
                            await self._send_volley(self._final_volley)
                            return
                        maybe_volley = read_volley()
                        if maybe_volley:
                            # We managed to get all of the peer's volley and generate a
                            # new one ourselves! break out of the 'for' loop and restart
                            # the timer.
                            volley_messages = new_volley
                            break
                if cscope.cancelled_caught:
                    # timeout expired, adjust timeout/mtu
                    # Good guidance here: https://tlswg.org/dtls13-spec/draft-ietf-tls-dtls13.html#name-timer-values
                    XX

    async def send(self, data):
        if not self._did_handshake:
            await self.do_handshake()
        self._ssl.write(data)
        await self.dtls.socket.sendto(self.peer_address, read_loop(self._ssl.bio_read))

    async def receive(self):
        if not self._did_handshake:
            await self.do_handshake()
        packet = await self._q.get()
        self._ssl.bio_write(packet)
        return read_loop(self._ssl.read)


class DTLS:
    def __init__(self, socket, *, incoming_packets_buffer=10):
        if socket.type != trio.socket.SOCK_DGRAM:
            raise BadPacket("DTLS requires a SOCK_DGRAM socket")
        self.socket = socket
        self.incoming_packets_buffer = incoming_packets_buffer
        self._token = trio.lowlevel.current_trio_token()
        # We don't need to track handshaking vs non-handshake connections
        # separately. We only keep one connection per remote address; as soon
        # as a peer provides a valid cookie, we can immediately tear down the
        # old connection.
        # {remote address: DTLSStream}
        self._streams = weakref.WeakValueDictionary()
        self._listening_context = None
        self._incoming_connections_q = Queue(float("inf"))

        trio.lowlevel.spawn_system_task(dtls_receive_loop, self)

    def __del__(self):
        # Close the socket in Trio context (if our Trio context still exists), so that
        # the background task gets notified about the closure and can exit.
        try:
            self._token.run_sync_soon(self.socket.close)
        except RuntimeError:
            pass

    def close(self):
        self.socket.close()
        for stream in self._streams.values():
            stream.close()
        self._incoming_connections_q._s.close()

    async def aclose(self):
        self.close()
        await trio.lowlevel.checkpoint()

    async def serve(self, ssl_context, async_fn, *args):
        if self._listening_context is not None:
            raise trio.BusyResourceError("another task is already listening")
        try:
            self._listening_context = ssl_context
            async with trio.open_nursery() as nursery:
                async for stream in self._incoming_connections_q._r:
                    nursery.start_soon(async_fn, stream, *args)
        finally:
            self._listening_context = None

    def _set_stream_for(self, address, stream):
        old_stream = self._streams.get(address)
        if old_stream is not None:
            old_stream._break(RuntimeError("replaced by a new DTLS association"))
        self._streams[address] = stream

    async def connect(self, address, ssl_context):
        stream = DTLSStream(self, address, ssl_context)
        self._set_stream_for(address, stream)
        await stream.do_handshake()
        return stream
