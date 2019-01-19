# ***********************************************************
# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******
# *************************************************************
from ._run import GLOBAL_RUN_CONTEXT, _NO_SEND
from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED


async def wait_readable(fd):
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_readable(fd)
    except AttributeError:
        raise RuntimeError('must be called from async context')


async def wait_writable(fd):
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_writable(fd)
    except AttributeError:
        raise RuntimeError('must be called from async context')


def notify_fd_close(fd):
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.notify_fd_close(fd)
    except AttributeError:
        raise RuntimeError('must be called from async context')
