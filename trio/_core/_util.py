import sys
from functools import wraps

__all__ = ["aiter_compat"]

def aiter_compat(aiter_impl):
    if sys.version_info < (3, 5, 2):
        @wraps(aiter_impl)
        async def __aiter__(*args, **kwargs):
            return aiter_impl(*args, **kwargs)
        return __aiter__
    else:
        return aiter_impl
