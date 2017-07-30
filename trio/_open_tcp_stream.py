from contextlib import contextmanager

import trio
from trio.socket import getaddrinfo, SOCK_STREAM, socket

__all__ = ["open_tcp_stream"]

# Implementation of RFC 6555 "Happy eyeballs"
# https://tools.ietf.org/html/rfc6555
#
# Basically, the problem here is that if we want to connect to some host, and
# DNS returns multiple IP addresses, then we don't know which of them will
# actually work -- it can happen that some of them are reachable, and some of
# them are not. One particularly common situation where this happens is on a
# host that thinks it has ipv6 connectivity, but really doesn't. But in
# principle this could happen for any kind of multi-home situation (e.g. the
# route to one mirror is down but another is up).
#
# The naive algorithm (e.g. the stdlib's socket.create_connection) would be to
# pick one of the IP addresses and try to connect; if that fails, try the
# next; etc. The problem with this is that TCP is stubborn, and if the first
# address is a blackhole then it might take a very long time (tens of seconds)
# before that connection attempt fails.
#
# That's where RFC 6555 comes in. It tells us that what we do is:
# - get the list of IPs from getaddrinfo, trusting the order it gives us (with
#   one exception noted in section 5.4)
# - start a connection attempt to the first IP
# - when this fails OR if it's still going after DELAY seconds, then start a
#   connection attempt to the second IP
# - when this fails OR if it's still going after another DELAY seconds, then
#   start a connection attempt to the third IP
# - ... repeat until we run out of IPs.
#
# Our implementation is similarly straightforward: we spawn a chain of tasks,
# where each one (a) waits until the previous connection has failed or DELAY
# seconds have passed, (b) spawns the next task, (c) attempts to connect. As
# soon as any task crashes or succeeds, we cancel all the tasks and return.
#
# Note: this currently doesn't attempt to cache any results, so if you make
# multiple connections to the same host it'll re-run the happy-eyeballs
# algorithm each time. RFC 6555 is pretty confusing about whether this is
# allowed. Section 4 describes an algorithm that attempts ipv4 and ipv6
# simultaneously, and then says "The client MUST cache information regarding
# the outcome of each connection attempt, and it uses that information to
# avoid thrashing the network with subsequent attempts." Then section 4.2 says
# "implementations MUST prefer the first IP address family returned by the
# host's address preference policy, unless implementing a stateful
# algorithm". Here "stateful" means "one that caches information about
# previous attempts". So my reading of this is that IF you're starting ipv4
# and ipv6 at the same time then you MUST cache the result for ~ten minutes,
# but IF you're "preferring" one protocol by trying it first (like we are),
# then you don't need to cache.
#
# Caching is quite tricky: to get it right you need to do things like detect
# when the network interfaces are reconfigured, and if you get it wrong then
# connection attempts basically just don't work. So we don't even try.

# "Firefox and Chrome use 300 ms"
# https://tools.ietf.org/html/rfc6555#section-6
# Though
#   https://www.researchgate.net/profile/Vaibhav_Bajpai3/publication/304568993_Measuring_the_Effects_of_Happy_Eyeballs/links/5773848e08ae6f328f6c284c/Measuring-the-Effects-of-Happy-Eyeballs.pdf
# claims that Firefox actually uses 0 ms, unless an about:config option is
# toggled and then it uses 250 ms.
DEFAULT_DELAY = 0.300

# How should we call getaddrinfo? In particular, should we use AI_ADDRCONFIG?
#
# The idea of AI_ADDRCONFIG is that it only returns addresses that might
# work. E.g., if getaddrinfo knows that you don't have any IPv6 connectivity,
# then it doesn't return any IPv6 addresses. And this is kinda nice, because
# it means maybe you can skip sending AAAA requests entirely. But in practice,
# it doesn't really work right.
#
# - on Linux/glibc, empirically, the default is to return all addresses, and
# with AI_ADDRCONFIG then it only returns IPv6 addresses if there is at least
# one non-loopback IPv6 address configured... but this can be a link-local
# address, so in practice I guess this is basically always configured if IPv6
# is enabled at all. OTOH if you pass in "::1" as the target address with
# AI_ADDRCONFIG and there's no *external* IPv6 address configured, you get an
# error. So AI_ADDRCONFIG mostly doesn't do anything, even when you would want
# it to, and when it does do something it might break things that would have
# worked.
#
# - on Windows 10, empirically, if no IPv6 address is configured then by
# default they are also suppressed from getaddrinfo (flags=0 and
# flags=AI_ADDRCONFIG seem to do the same thing). If you pass AI_ALL, then you
# get the full list.
# ...except for localhost! getaddrinfo("localhost", "80") gives me ::1, even
# though there's no ipv6 and other queries only return ipv4.
# If you pass in and IPv6 IP address as the target address, then that's always
# returned OK, even with AI_ADDRCONFIG set and no IPv6 configured.
#
# But I guess other versions of windows messed this up, judging from these bug
# reports:
# https://bugs.chromium.org/p/chromium/issues/detail?id=5234
# https://bugs.chromium.org/p/chromium/issues/detail?id=32522#c50
#
# So basically the options are either to use AI_ADDRCONFIG and then add some
# complicated special cases to work around its brokenness, or else don't use
# AI_ADDRCONFIG and accept that sometimes on legacy/misconfigured networks
# we'll waste 300 ms trying to connect to a blackholed destination.
#
# Twisted and Tornado always uses default flags. I think we'll do the same.

@contextmanager
def close_on_error(obj):
    try:
        yield obj
    except:
        obj.close()
        raise


def reorder_for_rfc_6555_section_5_4(targets):
    # RFC 6555 section 5.4 says that if getaddrinfo returns multiple address
    # families (e.g. IPv4 and IPv6), then you should make sure that your first
    # and second attempts use different families:
    #
    #    https://tools.ietf.org/html/rfc6555#section-5.4
    #
    # This function post-processes the results from getaddrinfo, in-place, to
    # satisfy this requirement.
    for i in range(1, len(targets)):
        if targets[i][0] != targets[0][0]:
            # Found the first entry with a different address family; move it
            # so that it becomes the second item on the list.
            if i != 1:
                targets.insert(1, targets.pop(i))
            break


def format_host_port(host, port):
    if ":" in host:
        return "[{}]:{}".format(host, port)
    else:
        return "{}:{}".format(host, port)


# Twisted's HostnameEndpoint has a good set of configurables:
#   https://twistedmatrix.com/documents/current/api/twisted.internet.endpoints.HostnameEndpoint.html
#
# - per-connection timeout
#   this doesn't seem useful -- we let you set a timeout on the whole thing
#   using trio's normal mechanisms, and that seems like enough
# - delay between attempts
# - bind address (but not port!)
#   they *don't* support multiple address bindings, like giving the ipv4 and
#   ipv6 addresses of the host.
#   I think maybe our semantics should be: we accept a list of bind addresses,
#   and we bind to the first one that is compatible with the
#   connection attempt we want to make, and if none are compatible then we
#   don't try to connect to that target.
#
# XX TODO: implement bind address support
#
# Actually, the best option is probably to be explicit: {AF_INET: "...",
#   AF_INET6: "..."}
# this might be simpler after
async def open_tcp_stream(
        host, port,
        *,
        # No trailing comma b/c bpo-9232 (fixed in py36)
        happy_eyeballs_delay=DEFAULT_DELAY
    ):
    """Connect to the given host and port over TCP.

    If the given ``host`` has multiple IP addresses associated with it, then
    we have a problem: which one do we use? One approach would be to attempt
    to connect to the first one, and then if that fails, attempt to connect to
    the second one ... until we've tried all of them. The problem with this is
    that if the first IP address is unreachable (for example, because it's an
    IPv6 address and our network discards IPv6 packets), then we might end up
    waiting tens of seconds for the first connection attempt to timeout before
    we try the second address. Another approach would be to attempt to connect
    to all of the addresses at the same time, and then use whichever address
    succeeds first. This will be fast, but it creates a lot of unnecessary
    network load.

    This function strikes a balance between these two extremes: it works its
    way through the available addresses in sequence, like the first approach;
    but, if an attempt hasn't succeeded or failed after
    ``happy_eyeballs_delay`` seconds, then it gets impatient and starts the
    next connection attempt in parallel. As soon as any one connection attempt
    succeeds, all the other attempts are cancelled. This way most connections
    involve minimal network load, but if one of the addresses is unreachable
    then it doesn't slow us down too much.

    This is a "happy eyeballs" algorithm, and roughly matches what Chrome
    does; see `RFC 6555 <https://tools.ietf.org/html/rfc6555>`__.

    Args:
      host (bytes or str): The host to connect to. Can be an IPv4 address,
          IPv6 address, or a hostname.
      port (int): The port to connect to.
      happy_eyeballs_delay (float): How many seconds to wait for each
          connection attempt to succeed or fail before getting impatient and
          starting another one in parallel. Set to :obj:`math.inf` if you want
          to limit to only one connection attempt at a time (like
          :func:`socket.create_connection`). Default: 0.3 (300 ms).

    Returns:
      SocketStream: a :class:`~trio.abc.Stream` connected to the given server.

    Raises:
      OSError: if the connection fails.

    See also:
      open_ssl_tcp_stream

    """

    if happy_eyeballs_delay is None:
        happy_eyeballs_delay = DEFAULT_DELAY

    targets = await getaddrinfo(host, port, type=SOCK_STREAM)

    # I don't think this can actually happen -- if there are no results,
    # getaddrinfo should have raised OSError instead of returning an empty
    # list. But let's be paranoid and handle it anyway:
    if not targets:
        msg = "no results found for hostname lookup: {}".format(
            format_host_port(host, port))
        raise OSError(msg)

    reorder_for_rfc_6555_section_5_4(targets)

    targets_iter = iter(targets)

    # This list records all the connection failures that we ignored.
    oserrors = []

    # It's possible for multiple connection attempts to succeed at the ~same
    # time; this list records all successful connections.
    winning_sockets = []

    # Sleep for the given amount of time, then kick off the next task and
    # start a connection attempt. On failure, expedite the next task; on
    # success, kill everything. Possible outcomes:
    # - records a failure in oserrors, returns None
    # - records a connected socket in winning_sockets, returns None
    # - crash (raises an unexpected exception)
    async def attempt_connect(nursery, previous_attempt_failed):
        # Wait until either the previous attempt failed, or the timeout
        # expires (unless this is the first invocation, in which case we just
        # go ahead).
        if previous_attempt_failed is not None:
            with trio.move_on_after(happy_eyeballs_delay):
                await previous_attempt_failed.wait()

        # Claim our target.
        try:
            *socket_args, _, target_sockaddr = next(targets_iter)
        except StopIteration:
            return

        # Then kick off the next attempt.
        this_attempt_failed = trio.Event()
        nursery.spawn(attempt_connect, nursery, this_attempt_failed)

        # Then make this invocation's attempt
        try:
            with close_on_error(socket(*socket_args)) as sock:
                await sock.connect(target_sockaddr)
        except OSError as exc:
            # This connection attempt failed, but the next one might
            # succeed. Save the error for later so we can report it if
            # everything fails, and tell the next attempt that it should go
            # ahead (if it hasn't already).
            oserrors.append(exc)
            this_attempt_failed.set()
        else:
            # Success! Save the winning socket and cancel all outstanding
            # connection attempts.
            winning_sockets.append(sock)
            nursery.cancel_scope.cancel()

    # Kick off the chain of connection attempts.
    async with trio.open_nursery() as nursery:
        nursery.spawn(attempt_connect, nursery, None)

    # All connection attempts complete, and no unexpected errors escaped. So
    # at this point the oserrors and winning_sockets lists are filled in.

    if winning_sockets:
        first_prize = winning_sockets.pop(0)
        for sock in winning_sockets:
            sock.close()
        return trio.SocketStream(first_prize)
    else:
        assert len(oserrors) == len(targets)
        msg = "all attempts to connect to {} failed".format(
            format_host_port(host, port))
        raise OSError(msg) from trio.MultiError(oserrors)
