# There are some tables here:
#   https://web.archive.org/web/20120206195747/https://msdn.microsoft.com/en-us/library/windows/desktop/ms740621(v=vs.85).aspx
# They appear to be wrong.
#
# See https://github.com/python-trio/trio/issues/928 for details and context

import socket
import errno

modes = ["default", "SO_REUSEADDR", "SO_EXCLUSIVEADDRUSE"]
bind_types = ["wildcard", "specific"]

def sock(mode):
    s = socket.socket(family=socket.AF_INET)
    if mode == "SO_REUSEADDR":
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    elif mode == "SO_EXCLUSIVEADDRUSE":
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    return s

def bind(sock, bind_type):
    if bind_type == "wildcard":
        sock.bind(("0.0.0.0", 12345))
    elif bind_type == "specific":
        sock.bind(("127.0.0.1", 12345))
    else:
        assert False

def table_entry(mode1, bind_type1, mode2, bind_type2):
    with sock(mode1) as sock1:
        bind(sock1, bind_type1)
        try:
            with sock(mode2) as sock2:
                bind(sock2, bind_type2)
        except OSError as exc:
            if exc.winerror == errno.WSAEADDRINUSE:
                return "INUSE"
            elif exc.winerror == errno.WSAEACCES:
                return "ACCESS"
            raise
        else:
            return "Success"

print("""
                                                       second bind
                               | """
+ " | ".join(["%-19s" % mode for mode in modes])
)

print("""                              """, end='')
for mode in modes:
    print(" | " + " | ".join(["%8s" % bind_type for bind_type in bind_types]), end='')

print("""
first bind                     -----------------------------------------------------------------"""
#            default | wildcard |    INUSE |  Success |   ACCESS |  Success |    INUSE |  Success
)

for i, mode1 in enumerate(modes):
    for j, bind_type1 in enumerate(bind_types):
        row = []
        for k, mode2 in enumerate(modes):
            for l, bind_type2 in enumerate(bind_types):
                entry = table_entry(mode1, bind_type1, mode2, bind_type2)
                row.append(entry)
                #print(mode1, bind_type1, mode2, bind_type2, entry)
        print("{:>19} | {:>8} | ".format(mode1, bind_type1)
              + " | ".join(["%8s" % entry for entry in row]))
