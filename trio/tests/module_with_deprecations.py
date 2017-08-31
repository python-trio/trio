regular = "hi"

from .. import _deprecate

_deprecate.enable_attribute_deprecations(__name__)

__deprecated_attributes__ = {
    "dep1":
        _deprecate.DeprecatedAttribute(
            "value1",
            "1.1",
            issue=1,
        ),
    "dep2":
        _deprecate.DeprecatedAttribute(
            "value2",
            "1.2",
            issue=1,
            instead="instead-string",
        ),
}
