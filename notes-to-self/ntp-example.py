# If you want to use IPv6, then:
# - replace AF_INET with AF_INET6 everywhere
# - use the hostname "2.pool.ntp.org"
#   (see: https://news.ntppool.org/2011/06/continuing-ipv6-deployment/)

import trio
import struct
import datetime

def make_query_packet():
    """Construct a UDP packet suitable for querying an NTP server to ask for
    the current time."""

    # The structure of an NTP packet is described here:
    #   https://tools.ietf.org/html/rfc5905#page-19
    # They're always 48 bytes long, unless you're using extensions, which we
    # aren't.
    packet = bytearray(48)

    # The first byte contains 3 subfields:
    # first 2 bits: 11, leap second status unknown
    # next 3 bits: 100, NTP version indicator, 0b100 == 4 = version 4
    # last 3 bits: 011, NTP mode indicator, 0b011 == 3 == "client"
    packet[0] = 0b11100011

    # For an outgoing request, all other fields can be left as zeros.

    return packet

def extract_transmit_timestamp(ntp_packet):
    """Given an NTP packet, extract the "transmit timestamp" field, as a
    Python datetime."""

    # The transmit timestamp is the time that the server sent its response.
    # It's stored in bytes 40-47 of the NTP packet. See:
    #   https://tools.ietf.org/html/rfc5905#page-19
    encoded_transmit_timestamp = ntp_packet[40:48]

    # The timestamp is stored in the "NTP timestamp format", which is a 32
    # byte count of whole seconds, followed by a 32 byte count of fractions of
    # a second. See:
    #   https://tools.ietf.org/html/rfc5905#page-13
    seconds, fraction = struct.unpack("!II", encoded_transmit_timestamp)

    # The timestamp is the number of seconds since January 1, 1900 (ignoring
    # leap seconds). To convert it to a datetime object, we do some simple
    # datetime arithmetic:
    base_time = datetime.datetime(1900, 1, 1)
    offset = datetime.timedelta(seconds=seconds + fraction / 2**32)
    return base_time + offset

async def main():
    print("Our clock currently reads (in UTC):", datetime.datetime.utcnow())

    # Look up some random NTP servers.
    # (See www.pool.ntp.org for information about the NTP pool.)
    servers = await trio.socket.getaddrinfo(
        "pool.ntp.org",               # host
        "ntp",                        # port
        family=trio.socket.AF_INET,   # IPv4
        type=trio.socket.SOCK_DGRAM,  # UDP
    )

    # Construct an NTP query packet.
    query_packet = make_query_packet()

    # Create a UDP socket
    udp_sock = trio.socket.socket(
        family=trio.socket.AF_INET,   # IPv4
        type=trio.socket.SOCK_DGRAM,  # UDP
    )

    # Use the socket to send the query packet to each of the servers.
    print("-- Sending queries --")
    for server in servers:
        address = server[-1]
        print("Sending to:", address)
        await udp_sock.sendto(query_packet, address)

    # Read responses from the socket.
    print("-- Reading responses (for 10 seconds) --")
    with trio.move_on_after(10):
        while True:
            # We accept packets up to 1024 bytes long (though in practice NTP
            # packets will be much shorter).
            data, address = await udp_sock.recvfrom(1024)
            print("Got response from:", address)
            transmit_timestamp = extract_transmit_timestamp(data)
            print("Their clock read (in UTC):", transmit_timestamp)

trio.run(main)
