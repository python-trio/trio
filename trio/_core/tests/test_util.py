import sys
import pytest

from .._util import *

def test_PyErr_SetExcInfo():
    assert sys.exc_info() == (None, None, None)
    try:
        raise ValueError("asdf")
    except:
        exc_info = sys.exc_info()
    orig_counts = [sys.getrefcount(obj) for obj in exc_info]
    assert sys.exc_info() == (None, None, None)
    PyErr_SetExcInfo(exc_info)
    assert sys.exc_info() == exc_info
    PyErr_SetExcInfo((None, None, None))
    assert sys.exc_info() == (None, None, None)
    final_counts = [sys.getrefcount(obj) for obj in exc_info]
    assert orig_counts == final_counts

    try:
        PyErr_SetExcInfo(exc_info)
        raise
    except ValueError as exc:
        assert exc.args == ("asdf",)
