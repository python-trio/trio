# This file is a hack to work around a quirk in Python's import machinery:
#
#    https://github.com/python-trio/trio/pull/1484#issuecomment-622574499
#
# It should be removed at the same time as the _DeprecatedAttribute("hazmat",
# ...) inside trio/__init__.py.

from ._deprecate import warn_deprecated

warn_deprecated("trio.hazmat", "0.15.0", issue=476, instead="trio.lowlevel")
del warn_deprecated

from .lowlevel import *
