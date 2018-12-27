from ._run import GLOBAL_RUN_CONTEXT, Runner
from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED


def current_kqueue():
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.current_kqueue()
    except AttributeError:
        raise RuntimeError('must be called from context')


def monitor_kevent(ident, filter):
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.monitor_kevent(
            ident, filter
        )
    except AttributeError:
        raise RuntimeError('must be called from context')


def wait_kevent(ident, filter, abort_func):
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.wait_kevent(
            ident, filter, abort_func
        )
    except AttributeError:
        raise RuntimeError('must be called from context')


def wait_readable(fd):
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.wait_readable(fd)
    except AttributeError:
        raise RuntimeError('must be called from context')


def wait_writable(fd):
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.wait_writable(fd)
    except AttributeError:
        raise RuntimeError('must be called from context')


def notify_fd_close(fd):
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.notify_fd_close(fd)
    except AttributeError:
        raise RuntimeError('must be called from context')
