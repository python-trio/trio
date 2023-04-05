from ._deprecate import warn_deprecated
import trio
from ._tests import *

warn_deprecated(
    trio.tests,
    "0.23.0",
    instead=trio._tests,
    issue="https://github.com/python-trio/trio/issues/274",
)
