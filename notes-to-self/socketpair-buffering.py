import socket

# Linux:
#   low values get rounded up to ~2-4 KB, so that's predictable
#   with low values, can queue up 6 one-byte sends (!)
#   with default values, can queue up 278 one-byte sends
#
# Windows:
#   if SNDBUF = 0 freezes, so that's useless
#   by default, buffers 655121
#   with both set to 1, buffers 525347
#   except sometimes it's less intermittently (?!?)
#
# macOS:
#   if bufsize = 1, can queue up 1 one-byte send
#   with default bufsize, can queue up 8192 one-byte sends
#   and bufsize = 0 is invalid (setsockopt errors out)

for bufsize in [1, None, 0]:
    a, b = socket.socketpair()
    a.setblocking(False)
    b.setblocking(False)

    a.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, 1)
    if bufsize is not None:
        a.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, bufsize)
        b.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, bufsize)

    try:
        for i in range(10000000):
            a.send(b"\x00")
    except BlockingIOError:
        pass

    print("setsockopt bufsize {}: {}".format(bufsize, i))
    a.close()
    b.close()
