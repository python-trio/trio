import _common  # isort: split

from trio._core._multierror import MultiError  # Bypass deprecation warnings


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
raise MultiError([exc1_fn(), exc2_fn()])
