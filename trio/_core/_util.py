import sys
from functools import wraps
import ctypes

__all__ = ["aiter_compat", "PyErr_SetExcInfo"]

def aiter_compat(aiter_impl):
    if sys.version_info < (3, 5, 2):
        @wraps(aiter_impl)
        async def __aiter__(*args, **kwargs):
            return aiter_impl(*args, **kwargs)
        return __aiter__
    else:
        return aiter_impl


_ctypes_PyErr_SetExcInfo = ctypes.pythonapi.PyErr_SetExcInfo
_ctypes_PyErr_SetExcInfo.restype = None
_ctypes_PyErr_SetExcInfo.argtypes = [ctypes.py_object] * 3
# PyErr_SetExcInfo steals references to the given objects
_ctypes_Py_IncRef = ctypes.pythonapi.Py_IncRef
_ctypes_Py_IncRef.restype = None
_ctypes_Py_IncRef.argtypes = [ctypes.py_object]

def PyErr_SetExcInfo(exc_info):
    def prep(arg):
        if arg is None:
            # convert None -> NULL
            return ctypes.py_object()
        else:
            _ctypes_Py_IncRef(arg)
            return arg
    prepped = [prep(obj) for obj in exc_info]
    _ctypes_PyErr_SetExcInfo(*prepped)
