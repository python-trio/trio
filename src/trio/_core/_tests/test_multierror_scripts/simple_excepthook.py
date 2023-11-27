import _common  # isort: split

import sys

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup


def exc1_fn() -> Exception:
    try:
        raise ValueError
    except Exception as exc:
        return exc


def exc2_fn() -> Exception:
    try:
        raise KeyError
    except Exception as exc:
        return exc


# This should be printed nicely, because Trio overrode sys.excepthook
raise ExceptionGroup("", [exc1_fn(), exc2_fn()])
