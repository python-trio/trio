from ._run import GLOBAL_RUN_CONTEXT, Runner
from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED


def current_iocp():
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.current_iocp()
    except AttributeError:
        raise RuntimeError('must be called from context')


def register_with_iocp(handle):
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.register_with_iocp(handle)
    except AttributeError:
        raise RuntimeError('must be called from context')


def wait_overlapped(handle, lpOverlapped):
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.wait_overlapped(
            handle, lpOverlapped
        )
    except AttributeError:
        raise RuntimeError('must be called from context')


def monitor_completion_key():
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.monitor_completion_key()
    except AttributeError:
        raise RuntimeError('must be called from context')


def wait_socket_readable(sock):
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.wait_socket_readable(sock)
    except AttributeError:
        raise RuntimeError('must be called from context')


def wait_socket_writable(sock):
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.wait_socket_writable(sock)
    except AttributeError:
        raise RuntimeError('must be called from context')


def notify_socket_close(sock):
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.notify_socket_close(sock)
    except AttributeError:
        raise RuntimeError('must be called from context')


def write_overlapped(handle, data, file_offset=0):
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.write_overlapped(
            handle, data, file_offset=file_offset
        )
    except AttributeError:
        raise RuntimeError('must be called from context')


def readinto_overlapped(handle, buffer, file_offset=0):
    """"""
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.readinto_overlapped(
            handle, buffer, file_offset=file_offset
        )
    except AttributeError:
        raise RuntimeError('must be called from context')
