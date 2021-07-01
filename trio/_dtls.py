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

import trio
from trio._util import NoPublicConstructor

MAX_UDP_PACKET_SIZE = 65527


def packet_header_overhead(sock):
    if sock.family == trio.socket.AF_INET:
        return 28
    else:
        return 48


def worst_case_mtu(sock):
    if sock.family == trio.socket.AF_INET:
        return 576 - packet_header_overhead(sock)
    else:
        return 1280 - packet_header_overhead(sock)


def best_guess_mtu(sock):
    return 1500 - packet_header_overhead(sock)


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


EPOCH_MASK = 0xFFFF << (6 * 8)


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
        record.content_type, record.version, record.epoch_seqno, len(record.payload),
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
    msg_len: int
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
    frag = payload[HANDSHAKE_MESSAGE_HEADER.size :]
    if len(frag) != frag_len:
        raise BadPacket("handshake fragment length doesn't match record length")
    return HandshakeFragment(msg_type, msg_len, msg_seq, frag_offset, frag_len, frag,)


def encode_handshake_fragment(hsf):
    hs_header = HANDSHAKE_MESSAGE_HEADER.pack(
        hsf.msg_type,
        hsf.msg_len.to_bytes(3, "big"),
        hsf.msg_seq,
        hsf.frag_offset.to_bytes(3, "big"),
        hsf.frag_len.to_bytes(3, "big"),
    )
    return hs_header + hsf.frag


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

        before_cookie = body[:cookie_len_offset]
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


# The final record in a handshake is Finished, which is encrypted, can't be fragmented
# (at least by us), and keeps its record number (because it's in a new epoch). So we
# just pass it through unchanged. (Fortunately, the payload is only a single hash value,
# so the largest it will ever be is 64 bytes for a 512-bit hash. Which is small enough
# that it never requires fragmenting to fit into a UDP packet.
@attr.frozen
class OpaqueHandshakeMessage:
    record: Record


# This takes a raw outgoing handshake volley that openssl generated, and
# reconstructs the handshake messages inside it, so that we can repack them
# into records while retransmitting. So the data ought to be well-behaved --
# it's not coming from the network.
def decode_volley_trusted(volley):
    messages = []
    messages_by_seq = {}
    for record in records_untrusted(volley):
        # ChangeCipherSpec isn't a handshake message, so it can't be fragmented.
        # Handshake messages with epoch > 0 are encrypted, so we can't fragment them
        # either. Fortunately, ChangeCipherSpec has a 1 byte payload, and the only
        # encrypted handshake message is Finished, whose payload is a single hash value
        # -- so 32 bytes for SHA-256, 64 for SHA-512, etc. Neither is going to be so
        # large that it has to be fragmented to fit into a single packet.
        if record.epoch_seqno & EPOCH_MASK:
            messages.append(OpaqueHandshakeMessage(record))
        elif record.content_type == ContentType.change_cipher_spec:
            messages.append(
                PseudoHandshakeMessage(
                    record.version, record.content_type, record.payload
                )
            )
        else:
            assert record.content_type == ContentType.handshake
            fragment = decode_handshake_fragment_untrusted(record.payload)
            msg_type = HandshakeType(fragment.msg_type)
            if fragment.msg_seq not in messages_by_seq:
                msg = HandshakeMessage(
                    record.version,
                    msg_type,
                    fragment.msg_seq,
                    bytearray(fragment.msg_len),
                )
                messages.append(msg)
                messages_by_seq[fragment.msg_seq] = msg
            else:
                msg = messages_by_seq[fragment.msg_seq]
            assert msg.msg_type == fragment.msg_type
            assert msg.msg_seq == fragment.msg_seq
            assert len(msg.body) == fragment.msg_len

            msg.body[
                fragment.frag_offset : fragment.frag_offset + fragment.frag_len
            ] = fragment.frag

    return messages


class RecordEncoder:
    def __init__(self):
        self._record_seq = count()

    def skip_first_record_number(self):
        assert next(self._record_seq) == 0

    def encode_volley(self, messages, mtu):
        packets = []
        packet = bytearray()
        for message in messages:
            if isinstance(message, OpaqueHandshakeMessage):
                encoded = encode_record(message.record)
                if mtu - len(packet) - len(encoded) <= 0:
                    packets.append(packet)
                    packet = bytearray()
                packet += encoded
                assert len(packet) <= mtu
            elif isinstance(message, PseudoHandshakeMessage):
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
                packet += message.payload
                assert len(packet) <= mtu
            else:
                msg_len_bytes = len(message.body).to_bytes(3, "big")
                frag_offset = 0
                frags_encoded = 0
                # If message.body is empty, then we still want to encode it in one
                # fragment, not zero.
                while frag_offset < len(message.body) or not frags_encoded:
                    space = (
                        mtu
                        - len(packet)
                        - RECORD_HEADER.size
                        - HANDSHAKE_MESSAGE_HEADER.size
                    )
                    if space <= 0:
                        packets.append(packet)
                        packet = bytearray()
                        continue
                    frag = message.body[frag_offset : frag_offset + space]
                    frag_offset_bytes = frag_offset.to_bytes(3, "big")
                    frag_len_bytes = len(frag).to_bytes(3, "big")
                    frag_offset += len(frag)

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

                    frags_encoded += 1
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

# XX maybe the cookie should also sign the *local* address, so you can't take a cookie
# from one socket and use it on another socket on the same trio? or just generate the
# key in each call to 'serve'.

COOKIE_REFRESH_INTERVAL = 30  # seconds
KEY = None
KEY_BYTES = 8
COOKIE_HASH = "sha256"
SALT_BYTES = 8


def _current_cookie_tick():
    return int(trio.current_time() / COOKIE_REFRESH_INTERVAL)


# Simple deterministic and invertible serializer -- i.e., a useful tool for converting
# structured data into something we can cryptographically sign.
def _signable(*fields):
    out = []
    for field in fields:
        out.append(struct.pack("!Q", len(field)))
        out.append(field)
    return b"".join(out)


def _make_cookie(salt, tick, address, client_hello_bits):
    assert len(salt) == SALT_BYTES

    global KEY
    if KEY is None:
        KEY = os.urandom(KEY_BYTES)

    signable_data = _signable(
        salt,
        struct.pack("!Q", tick),
        # address is a mix of strings and ints, and variable length, so pack
        # it into a single nested field
        _signable(*(str(part).encode() for part in address)),
        client_hello_bits,
    )

    return salt + hmac.digest(KEY, signable_data, COOKIE_HASH)


def valid_cookie(cookie, address, client_hello_bits):
    if len(cookie) > SALT_BYTES:
        salt = cookie[:SALT_BYTES]

        tick = _current_cookie_tick()

        cur_cookie = _make_cookie(salt, tick, address, client_hello_bits)
        old_cookie = _make_cookie(salt, tick - 1, address, client_hello_bits)

        # I doubt using a short-circuiting 'or' here would leak any meaningful
        # information, but why risk it when '|' is just as easy.
        return hmac.compare_digest(cookie, cur_cookie) | hmac.compare_digest(
            cookie, old_cookie
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
        frag=body,
    )
    payload = encode_handshake_fragment(hs)

    packet = encode_record(
        Record(ContentType.handshake, ProtocolVersion.DTLS10, epoch_seqno, payload)
    )
    return packet


class _Queue:
    def __init__(self, incoming_packets_buffer):
        self.s, self.r = trio.open_memory_channel(incoming_packets_buffer)


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
        epoch_seqno, cookie, bits = decode_client_hello_untrusted(packet)
    except BadPacket:
        return

    if not valid_cookie(cookie, address, bits):
        challenge_packet = challenge_for(address, epoch_seqno, bits)
        try:
            async with dtls._send_lock:
                await dtls.socket.sendto(challenge_packet, address)
        except (OSError, trio.ClosedResourceError):
            pass
    else:
        # We got a real, valid ClientHello!
        stream = DTLSStream._create(dtls, address, dtls._listening_context)
        try:
            stream._inject_client_hello_untrusted(packet)
        except BadPacket:
            # ...or, well, OpenSSL didn't like it, so I guess we didn't.
            return
        old_stream = dtls._streams.get(address)
        if old_stream is not None:
            if old_stream._client_hello == packet:
                # ...but it's just a duplicate of a packet we got before, so never mind.
                return
            else:
                # Ok, this *really is* a new handshake; the old stream should go away.
                old_stream._replaced()
        dtls._streams[address] = stream
        dtls._incoming_connections_q.s.send_nowait(stream)


async def dtls_receive_loop(dtls):
    sock = dtls.socket
    dtls_ref = weakref.ref(dtls)
    del dtls
    while True:
        try:
            packet, address = await sock.recvfrom(MAX_UDP_PACKET_SIZE)
        except trio.ClosedResourceError:
            return
        except OSError as exc:
            if exc.errno in (errno.EBADF, errno.ENOTSOCK):
                # Socket was closed
                return
            else:
                # Some weird error, e.g. apparently some versions of Windows can do
                # ECONNRESET here to report that some previous UDP packet got an ICMP
                # Port Unreachable:
                #   https://bobobobo.wordpress.com/2009/05/17/udp-an-existing-connection-was-forcibly-closed-by-the-remote-host/
                # We'll assume that whatever it is, it's a transient problem.
                continue
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
                    # putting it into the queue and letting the receiver do it, because
                    # there's no guarantee that anyone is reading from the queue,
                    # because we think the handshake is done!
                    try:
                        await stream._resend_final_volley()
                    except trio.ClosedResourceError:
                        return
                else:
                    try:
                        stream._q.s.send_nowait(packet)
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
        self._client_hello = None
        self._did_handshake = False
        # These are mandatory for all DTLS connections. OP_NO_QUERY_MTU is required to
        # stop openssl from trying to query the memory BIO's MTU and then breaking, and
        # OP_NO_RENEGOTIATION disables renegotiation, which is too complex for us to
        # support and isn't useful anyway -- especially for DTLS where it's equivalent
        # to just performing a new handshake.
        ctx.set_options(SSL.OP_NO_QUERY_MTU | SSL.OP_NO_RENEGOTIATION)
        self._ssl = SSL.Connection(ctx)
        self._mtu = None
        # This calls self._ssl.set_ciphertext_mtu, which is important, because if you
        # don't call it then openssl doesn't work.
        self.set_ciphertext_mtu(best_guess_mtu(self.dtls.socket))
        self._replaced = False
        self._closed = False
        self._q = _Queue(dtls.incoming_packets_buffer)
        self._handshake_lock = trio.Lock()
        self._record_encoder = RecordEncoder()

    def _replaced(self):
        self._replaced = True
        # Any packets we already received could maybe possibly still be processed, but
        # there are no more coming. So we close this on the sender side.
        self._q.s.close()

    def _check_replaced(self):
        if self._replaced:
            raise BrokenResourceError(
                "peer tore down this connection to start a new one"
            )

    def set_ciphertext_mtu(self, new_mtu):
        self._mtu = new_mtu
        self._ssl.set_ciphertext_mtu(new_mtu)

    def get_cleartext_mtu(self):
        return self._ssl.get_cleartext_mtu()

    # XX on systems where we can (maybe just Linux?) take advantage of the kernel's PMTU
    # estimate

    # XX should we send close-notify when closing? It seems particularly pointless for
    # DTLS where packets are all independent and can be lost anyway. We do at least need
    # to handle receiving it properly though, which might be easier if we send it...

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.dtls._streams.get(self.peer_address) is self:
            del self.dtls._streams[self.peer_address]
        # Will wake any tasks waiting on self._q.get with a
        # ClosedResourceError
        self._q.r.close()

    async def aclose(self):
        self.close()
        await trio.lowlevel.checkpoint()

    def _inject_client_hello_untrusted(self, packet):
        self._client_hello = packet
        self._ssl.bio_write(packet)
        # If we're on the server side, then we already sent record 0 as our cookie
        # challenge. So we want to start the handshake proper with record 1.
        self._record_encoder.skip_first_record_number()
        # We've already validated this cookie. But, we still have to call DTLSv1_listen
        # so OpenSSL thinks that it's verified the cookie. The problem is that
        # if you're doing cookie challenges, then the actual ClientHello has msg_seq=1
        # instead of msg_seq=0, and OpenSSL will refuse to process a ClientHello with
        # msg_seq=1 unless you've called DTLSv1_listen. It also gets OpenSSL to bump the
        # outgoing ServerHello's msg_seq to 1.
        try:
            self._ssl.DTLSv1_listen()
        except SSL.Error:
            raise BadPacket

    async def _send_volley(self, volley_messages):
        packets = self._record_encoder.encode_volley(volley_messages, self._mtu)
        for packet in packets:
            async with self.dtls._send_lock:
                await self.dtls.socket.sendto(packet, self.peer_address)

    async def _resend_final_volley(self):
        await self._send_volley(self._final_volley)

    async def do_handshake(self, *, initial_retransmit_timeout=1.0):
        async with self._handshake_lock:
            if self._did_handshake:
                return

            timeout = initial_retransmit_timeout
            volley_messages = []
            volley_failed_sends = 0

            def read_volley():
                volley_bytes = _read_loop(self._ssl.bio_read)
                new_volley_messages = decode_volley_trusted(volley_bytes)
                if (
                    new_volley_messages
                    and volley_messages
                    and new_volley_messages[0].msg_seq == volley_messages[0].msg_seq
                ):
                    # openssl decided to retransmit; discard because we handle
                    # retransmits ourselves
                    return []
                else:
                    return new_volley_messages

            # If we're a client, we send the initial volley. If we're a server, then
            # the initial ClientHello has already been inserted into self._ssl's
            # read BIO. So either way, we start by generating a new volley.
            try:
                self._ssl.do_handshake()
            except SSL.WantReadError:
                pass
            volley_messages = read_volley()
            # If we don't have messages to send in our initial volley, then something
            # has gone very wrong. (I'm not sure this can actually happen without an
            # error from OpenSSL, but we check just in case.)
            if not volley_messages:
                raise SSL.Error("something wrong with peer's ClientHello")

            while True:
                # -- at this point, we need to either send or re-send a volley --
                assert volley_messages
                await self._send_volley(volley_messages)
                # -- then this is where we wait for a reply --
                with trio.move_on_after(10) as cscope:
                    async for packet in self._q.r:
                        self._ssl.bio_write(packet)
                        try:
                            self._ssl.do_handshake()
                        except SSL.WantReadError:
                            pass
                        else:
                            # No exception -> the handshake is done, and we can
                            # switch into data transfer mode.
                            self._did_handshake = True
                            # Might be empty, but that's ok -- we'll just send no
                            # packets.
                            self._final_volley = read_volley()
                            await self._send_volley(self._final_volley)
                            return
                        maybe_volley = read_volley()
                        if maybe_volley:
                            # We managed to get all of the peer's volley and generate a
                            # new one ourselves! break out of the 'for' loop and restart
                            # the timer.
                            volley_messages = maybe_volley
                            # "Implementations SHOULD retain the current timer value
                            # until a transmission without loss occurs, at which time
                            # the value may be reset to the initial value."
                            if volley_failed_sends == 0:
                                timeout = initial_retransmit_timeout
                            volley_failed_sends = 0
                            break
                    else:
                        assert self._replaced
                        self._check_replaced()
                if cscope.cancelled_caught:
                    # Timeout expired. Double timeout for backoff, with a limit of 60
                    # seconds (this matches what openssl does, and also the
                    # recommendation in draft-ietf-tls-dtls13).
                    timeout = min(2 * timeout, 60.0)
                    volley_failed_sends += 1
                    if volley_failed_sends == 2:
                        # We tried sending this twice and they both failed. Maybe our
                        # PMTU estimate is wrong? Let's try dropping it to the minimum
                        # and hope that helps.
                        self.set_ciphertext_mtu(
                            min(self._mtu, worst_case_mtu(self.dtls.socket))
                        )

    async def send(self, data):
        if self._closed:
            raise trio.ClosedResourceError
        if not self._did_handshake:
            await self.do_handshake()
        self._check_replaced()
        self._ssl.write(data)
        async with self.dtls._send_lock:
            await self.dtls.socket.sendto(
                _read_loop(self._ssl.bio_read), self.peer_address
            )

    async def receive(self):
        if not self._did_handshake:
            await self.do_handshake()
        try:
            packet = await self._q.r.receive()
        except trio.EndOfChannel:
            assert self._replaced
            self._check_replaced()
        self._ssl.bio_write(packet)
        return _read_loop(self._ssl.read)


class DTLS:
    def __init__(self, socket, *, incoming_packets_buffer=10):
        # We do this lazily on first construction, so only people who actually use DTLS
        # have to install PyOpenSSL.
        global SSL
        from OpenSSL import SSL

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
        self._incoming_connections_q = _Queue(float("inf"))
        self._send_lock = trio.Lock()

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
        self._incoming_connections_q.s.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    async def serve(
        self, ssl_context, async_fn, *args, task_status=trio.TASK_STATUS_IGNORED
    ):
        if self._listening_context is not None:
            raise trio.BusyResourceError("another task is already listening")
        # We do cookie verification ourselves, so tell OpenSSL not to worry about it.
        # (See also _inject_client_hello_untrusted.)
        ssl_context.set_cookie_verify_callback(lambda *_: True)
        try:
            self._listening_context = ssl_context
            task_status.started()
            async with trio.open_nursery() as nursery:
                async for stream in self._incoming_connections_q.r:
                    nursery.start_soon(async_fn, stream, *args)
        finally:
            self._listening_context = None

    def _set_stream_for(self, address, stream):
        old_stream = self._streams.get(address)
        if old_stream is not None:
            old_stream._break(RuntimeError("replaced by a new DTLS association"))
        self._streams[address] = stream

    async def connect(self, address, ssl_context):
        stream = DTLSStream._create(self, address, ssl_context)
        stream._ssl.set_connect_state()
        self._set_stream_for(address, stream)
        await stream.do_handshake()
        return stream
