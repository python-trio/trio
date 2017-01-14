# Our general layout:
# - trio/hazmat/... is the self-contained core library.
#   It does various shenanigans to export a consistent "core API", but which
#   has a number of limitations and rough edges.
# - trio/*.py define a set of more usable tools on top of this. They import
#   from hazmat and from each other.
# - This file pulls together the friendly public API, by re-exporting the more
#   innocuous bits of the hazmat layer + the the tools from trio/*.py. No-one
#   imports it internally; it's only for public consumption.

__all__ = []

from .hazmat._exceptions import *
__all__ += _hazmat._exceptions.__all__

from .hazmat._result import *
__all__ += _hazmat._result.__all__

from .hazmat._runner import *
__all__ += _hazmat._runner.__all__

import .hazmat
for _reexport in [
        "current_time", "current_profiler", "spawn", "current_task",
        ]:
    globals[_reexport] = getattr(hazmat, _reexport)
    __all__.append(_reexport)
del _reexport
