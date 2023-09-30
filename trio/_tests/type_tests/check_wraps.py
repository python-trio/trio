# https://github.com/python-trio/trio/issues/2775#issuecomment-1702267589
# (except platform independent...)
import typing_extensions

import trio


async def fn(s: trio.SocketStream) -> None:
    result = await s.socket.sendto(b"a", "h")
    typing_extensions.assert_type(result, int)
