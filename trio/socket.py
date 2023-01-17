# This is a public namespace, so we don't want to expose any non-underscored
# attributes that aren't actually part of our public API. But it's very
# annoying to carefully always use underscored names for module-level
# temporaries, imports, etc. when implementing the module. So we put the
# implementation in an underscored module, and then re-export the public parts
# here.
# We still have some underscore names though but only a few.

import sys
import typing as _t

from . import _socket

# The socket module exports a bunch of platform-specific constants. We want to
# re-export them. Since the exact set of constants varies depending on Python
# version, platform, the libc installed on the system where Python was built,
# etc., we figure out which constants to re-export dynamically at runtime (see
# below). But that confuses static analysis tools like jedi and mypy. So this
# import statement statically lists every constant that *could* be
# exported. It always fails at runtime, since no single Python build exports
# all these constants, but it lets static analysis tools understand what's
# going on. There's a test in test_exports.py to make sure that the list is
# kept up to date.
try:
    # fmt: off
    from socket import (AF_ALG, AF_APPLETALK, AF_ASH,  # type: ignore
                        AF_ATMPVC, AF_ATMSVC, AF_AX25, AF_BLUETOOTH, AF_BRIDGE,
                        AF_CAN, AF_ECONET, AF_INET, AF_INET6, AF_IPX, AF_IRDA,
                        AF_KEY, AF_LINK, AF_LLC, AF_NETBEUI, AF_NETLINK,
                        AF_NETROM, AF_PACKET, AF_PPPOX, AF_QIPCRTR, AF_RDS,
                        AF_ROSE, AF_ROUTE, AF_SECURITY, AF_SNA, AF_SYSTEM,
                        AF_TIPC, AF_UNIX, AF_UNSPEC, AF_VSOCK, AF_WANPIPE,
                        AF_X25, AI_ADDRCONFIG, AI_ALL, AI_CANONNAME,
                        AI_DEFAULT, AI_MASK, AI_NUMERICHOST, AI_NUMERICSERV,
                        AI_PASSIVE, AI_V4MAPPED, AI_V4MAPPED_CFG,
                        ALG_OP_DECRYPT, ALG_OP_ENCRYPT, ALG_OP_SIGN,
                        ALG_OP_VERIFY, ALG_SET_AEAD_ASSOCLEN,
                        ALG_SET_AEAD_AUTHSIZE, ALG_SET_IV, ALG_SET_KEY,
                        ALG_SET_OP, ALG_SET_PUBKEY, BDADDR_ANY, BDADDR_LOCAL,
                        BTPROTO_HCI, BTPROTO_L2CAP, BTPROTO_RFCOMM,
                        BTPROTO_SCO, CAN_BCM, CAN_BCM_CAN_FD_FRAME,
                        CAN_BCM_RX_ANNOUNCE_RESUME, CAN_BCM_RX_CHANGED,
                        CAN_BCM_RX_CHECK_DLC, CAN_BCM_RX_DELETE,
                        CAN_BCM_RX_FILTER_ID, CAN_BCM_RX_NO_AUTOTIMER,
                        CAN_BCM_RX_READ, CAN_BCM_RX_RTR_FRAME,
                        CAN_BCM_RX_SETUP, CAN_BCM_RX_STATUS,
                        CAN_BCM_RX_TIMEOUT, CAN_BCM_SETTIMER,
                        CAN_BCM_STARTTIMER, CAN_BCM_TX_ANNOUNCE,
                        CAN_BCM_TX_COUNTEVT, CAN_BCM_TX_CP_CAN_ID,
                        CAN_BCM_TX_DELETE, CAN_BCM_TX_EXPIRED, CAN_BCM_TX_READ,
                        CAN_BCM_TX_RESET_MULTI_IDX, CAN_BCM_TX_SEND,
                        CAN_BCM_TX_SETUP, CAN_BCM_TX_STATUS, CAN_EFF_FLAG,
                        CAN_EFF_MASK, CAN_ERR_FLAG, CAN_ERR_MASK, CAN_ISOTP,
                        CAN_J1939, CAN_RAW, CAN_RAW_ERR_FILTER,
                        CAN_RAW_FD_FRAMES, CAN_RAW_FILTER,
                        CAN_RAW_JOIN_FILTERS, CAN_RAW_LOOPBACK,
                        CAN_RAW_RECV_OWN_MSGS, CAN_RTR_FLAG, CAN_SFF_MASK,
                        CAPI, CMSG_LEN, CMSG_SPACE, EAGAIN, EAI_ADDRFAMILY,
                        EAI_AGAIN, EAI_BADFLAGS, EAI_BADHINTS, EAI_FAIL,
                        EAI_FAMILY, EAI_MAX, EAI_MEMORY, EAI_NODATA,
                        EAI_NONAME, EAI_OVERFLOW, EAI_PROTOCOL, EAI_SERVICE,
                        EAI_SOCKTYPE, EAI_SYSTEM, EBADF, EWOULDBLOCK,
                        FD_SETSIZE, HCI_DATA_DIR, HCI_FILTER, HCI_TIME_STAMP,
                        INADDR_ALLHOSTS_GROUP, INADDR_ANY, INADDR_BROADCAST,
                        INADDR_LOOPBACK, INADDR_MAX_LOCAL_GROUP, INADDR_NONE,
                        INADDR_UNSPEC_GROUP, IOCTL_VM_SOCKETS_GET_LOCAL_CID,
                        IP_ADD_MEMBERSHIP, IP_DEFAULT_MULTICAST_LOOP,
                        IP_DEFAULT_MULTICAST_TTL, IP_DROP_MEMBERSHIP,
                        IP_HDRINCL, IP_MAX_MEMBERSHIPS, IP_MULTICAST_IF,
                        IP_MULTICAST_LOOP, IP_MULTICAST_TTL, IP_OPTIONS,
                        IP_RECVDSTADDR, IP_RECVOPTS, IP_RECVRETOPTS,
                        IP_RECVTOS, IP_RETOPTS, IP_TOS, IP_TRANSPARENT, IP_TTL,
                        IPPORT_RESERVED, IPPORT_USERRESERVED, IPPROTO_AH,
                        IPPROTO_CBT, IPPROTO_DSTOPTS, IPPROTO_EGP, IPPROTO_EON,
                        IPPROTO_ESP, IPPROTO_FRAGMENT, IPPROTO_GGP,
                        IPPROTO_GRE, IPPROTO_HELLO, IPPROTO_HOPOPTS,
                        IPPROTO_ICLFXBM, IPPROTO_ICMP, IPPROTO_ICMPV6,
                        IPPROTO_IDP, IPPROTO_IGMP, IPPROTO_IGP, IPPROTO_IP,
                        IPPROTO_IPCOMP, IPPROTO_IPIP, IPPROTO_IPV4,
                        IPPROTO_L2TP, IPPROTO_MAX, IPPROTO_MOBILE,
                        IPPROTO_MPTCP, IPPROTO_ND, IPPROTO_NONE, IPPROTO_PGM,
                        IPPROTO_PIM, IPPROTO_PUP, IPPROTO_RAW, IPPROTO_RDP,
                        IPPROTO_ROUTING, IPPROTO_RSVP, IPPROTO_SCTP,
                        IPPROTO_ST, IPPROTO_TCP, IPPROTO_TP, IPPROTO_UDP,
                        IPPROTO_UDPLITE, IPPROTO_XTP, IPV6_CHECKSUM,
                        IPV6_DONTFRAG, IPV6_DSTOPTS, IPV6_HOPLIMIT,
                        IPV6_HOPOPTS, IPV6_JOIN_GROUP, IPV6_LEAVE_GROUP,
                        IPV6_MULTICAST_HOPS, IPV6_MULTICAST_IF,
                        IPV6_MULTICAST_LOOP, IPV6_NEXTHOP, IPV6_PATHMTU,
                        IPV6_PKTINFO, IPV6_RECVDSTOPTS, IPV6_RECVHOPLIMIT,
                        IPV6_RECVHOPOPTS, IPV6_RECVPATHMTU, IPV6_RECVPKTINFO,
                        IPV6_RECVRTHDR, IPV6_RECVTCLASS, IPV6_RTHDR,
                        IPV6_RTHDR_TYPE_0, IPV6_RTHDRDSTOPTS, IPV6_TCLASS,
                        IPV6_UNICAST_HOPS, IPV6_USE_MIN_MTU, IPV6_V6ONLY,
                        J1939_EE_INFO_NONE, J1939_EE_INFO_TX_ABORT,
                        J1939_FILTER_MAX, J1939_IDLE_ADDR,
                        J1939_MAX_UNICAST_ADDR, J1939_NLA_BYTES_ACKED,
                        J1939_NLA_PAD, J1939_NO_ADDR, J1939_NO_NAME,
                        J1939_NO_PGN, J1939_PGN_ADDRESS_CLAIMED,
                        J1939_PGN_ADDRESS_COMMANDED, J1939_PGN_MAX,
                        J1939_PGN_PDU1_MAX, J1939_PGN_REQUEST, LOCAL_PEERCRED,
                        MSG_BCAST, MSG_CMSG_CLOEXEC, MSG_CONFIRM, MSG_CTRUNC,
                        MSG_DONTROUTE, MSG_DONTWAIT, MSG_EOF, MSG_EOR,
                        MSG_ERRQUEUE, MSG_FASTOPEN, MSG_MCAST, MSG_MORE,
                        MSG_NOSIGNAL, MSG_NOTIFICATION, MSG_OOB, MSG_PEEK,
                        MSG_TRUNC, MSG_WAITALL, NETLINK_CRYPTO,
                        NETLINK_DNRTMSG, NETLINK_FIREWALL, NETLINK_IP6_FW,
                        NETLINK_NFLOG, NETLINK_ROUTE, NETLINK_USERSOCK,
                        NETLINK_XFRM, NI_DGRAM, NI_MAXHOST, NI_MAXSERV,
                        NI_NAMEREQD, NI_NOFQDN, NI_NUMERICHOST, NI_NUMERICSERV,
                        PACKET_BROADCAST, PACKET_FASTROUTE, PACKET_HOST,
                        PACKET_LOOPBACK, PACKET_MULTICAST, PACKET_OTHERHOST,
                        PACKET_OUTGOING, PF_CAN, PF_PACKET, PF_RDS, PF_SYSTEM,
                        POLLERR, POLLHUP, POLLIN, POLLMSG, POLLNVAL, POLLOUT,
                        POLLPRI, POLLRDBAND, POLLRDNORM, POLLWRNORM,
                        RCVALL_MAX, RCVALL_OFF, RCVALL_ON,
                        RCVALL_SOCKETLEVELONLY, SCM_CREDENTIALS, SCM_CREDS,
                        SCM_J1939_DEST_ADDR, SCM_J1939_DEST_NAME,
                        SCM_J1939_ERRQUEUE, SCM_J1939_PRIO, SCM_RIGHTS,
                        SHUT_RD, SHUT_RDWR, SHUT_WR, SIO_KEEPALIVE_VALS,
                        SIO_LOOPBACK_FAST_PATH, SIO_RCVALL, SIOCGIFINDEX,
                        SIOCGIFNAME, SO_ACCEPTCONN, SO_BINDTODEVICE,
                        SO_BROADCAST, SO_DEBUG, SO_DOMAIN, SO_DONTROUTE,
                        SO_ERROR, SO_EXCLUSIVEADDRUSE, SO_INCOMING_CPU,
                        SO_J1939_ERRQUEUE, SO_J1939_FILTER, SO_J1939_PROMISC,
                        SO_J1939_SEND_PRIO, SO_KEEPALIVE, SO_LINGER, SO_MARK,
                        SO_OOBINLINE, SO_PASSCRED, SO_PASSSEC, SO_PEERCRED,
                        SO_PEERSEC, SO_PRIORITY, SO_PROTOCOL, SO_RCVBUF,
                        SO_RCVLOWAT, SO_RCVTIMEO, SO_REUSEADDR, SO_REUSEPORT,
                        SO_SETFIB, SO_SNDBUF, SO_SNDLOWAT, SO_SNDTIMEO,
                        SO_TYPE, SO_USELOOPBACK, SO_VM_SOCKETS_BUFFER_MAX_SIZE,
                        SO_VM_SOCKETS_BUFFER_MIN_SIZE,
                        SO_VM_SOCKETS_BUFFER_SIZE, SOCK_CLOEXEC, SOCK_DGRAM,
                        SOCK_NONBLOCK, SOCK_RAW, SOCK_RDM, SOCK_SEQPACKET,
                        SOCK_STREAM, SOL_ALG, SOL_CAN_BASE, SOL_CAN_RAW,
                        SOL_HCI, SOL_IP, SOL_RDS, SOL_SOCKET, SOL_TCP,
                        SOL_TIPC, SOL_UDP, SOMAXCONN, SYSPROTO_CONTROL,
                        TCP_CONGESTION, TCP_CORK, TCP_DEFER_ACCEPT,
                        TCP_FASTOPEN, TCP_INFO, TCP_KEEPALIVE, TCP_KEEPCNT,
                        TCP_KEEPIDLE, TCP_KEEPINTVL, TCP_LINGER2, TCP_MAXSEG,
                        TCP_NODELAY, TCP_NOTSENT_LOWAT, TCP_QUICKACK,
                        TCP_SYNCNT, TCP_USER_TIMEOUT, TCP_WINDOW_CLAMP,
                        TIPC_ADDR_ID, TIPC_ADDR_NAME, TIPC_ADDR_NAMESEQ,
                        TIPC_CFG_SRV, TIPC_CLUSTER_SCOPE, TIPC_CONN_TIMEOUT,
                        TIPC_CRITICAL_IMPORTANCE, TIPC_DEST_DROPPABLE,
                        TIPC_HIGH_IMPORTANCE, TIPC_IMPORTANCE,
                        TIPC_LOW_IMPORTANCE, TIPC_MEDIUM_IMPORTANCE,
                        TIPC_NODE_SCOPE, TIPC_PUBLISHED, TIPC_SRC_DROPPABLE,
                        TIPC_SUB_CANCEL, TIPC_SUB_PORTS, TIPC_SUB_SERVICE,
                        TIPC_SUBSCR_TIMEOUT, TIPC_TOP_SRV, TIPC_WAIT_FOREVER,
                        TIPC_WITHDRAWN, TIPC_ZONE_SCOPE, UDPLITE_RECV_CSCOV,
                        UDPLITE_SEND_CSCOV, VM_SOCKETS_INVALID_VERSION,
                        VMADDR_CID_ANY, VMADDR_CID_HOST, VMADDR_PORT_ANY)

    # fmt: on
except ImportError:
    pass

# Dynamically re-export whatever constants this particular Python happens to
# have:
import socket as _stdlib_socket

_bad_symbols: _t.Set[str] = set()
if sys.platform == "win32":
    # See https://github.com/python-trio/trio/issues/39
    # Do not import for windows platform
    # (you can still get it from stdlib socket, of course, if you want it)
    _bad_symbols.add("SO_REUSEADDR")

globals().update(
    {
        _name: getattr(_stdlib_socket, _name)
        for _name in _stdlib_socket.__all__  # type: ignore
        if _name.isupper() and _name not in _bad_symbols
    }
)

# import the overwrites
from ._socket import (
    SocketType,
    from_stdlib_socket,
    fromfd,
    getaddrinfo,
    getnameinfo,
    getprotobyname,
    set_custom_hostname_resolver,
    set_custom_socket_factory,
    socket,
    socketpair,
)

# not always available so expose only if
if sys.platform == "win32" or not _t.TYPE_CHECKING:
    try:
        from ._socket import fromshare
    except ImportError:
        pass

# expose these functions to trio.socket
from socket import (
    gaierror,
    gethostname,
    herror,
    htonl,
    htons,
    inet_aton,
    inet_ntoa,
    inet_ntop,
    inet_pton,
    ntohs,
)

# not always available so expose only if
if sys.platform != "win32" or not _t.TYPE_CHECKING:
    try:
        from socket import if_indextoname, if_nameindex, if_nametoindex, sethostname
    except ImportError:
        pass

# get names used by Trio that we define on our own
from ._socket import IPPROTO_IPV6

if _t.TYPE_CHECKING:
    IP_BIND_ADDRESS_NO_PORT: int
else:
    try:
        IP_BIND_ADDRESS_NO_PORT
    except NameError:
        if sys.platform == "linux":
            IP_BIND_ADDRESS_NO_PORT = 24

del sys
