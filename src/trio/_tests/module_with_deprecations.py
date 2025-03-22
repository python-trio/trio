regular = "hi"

# Make sure that we don't trigger infinite recursion when accessing module
# attributes in between calling enable_attribute_deprecations and defining
# __deprecated_attributes__:
import sys
from typing import TYPE_CHECKING

from .. import _deprecate

this_mod = sys.modules[__name__]
assert this_mod.regular == "hi"
assert not hasattr(this_mod, "dep1")

if not TYPE_CHECKING:
    __getattr__ = _deprecate.getattr_for_deprecated_attributes(
        __name__,
        {
            "dep1": _deprecate.DeprecatedAttribute("value1", "1.1", issue=1),
            "dep2": _deprecate.DeprecatedAttribute(
                "value2",
                "1.2",
                issue=1,
                instead="instead-string",
            ),
        },
    )
