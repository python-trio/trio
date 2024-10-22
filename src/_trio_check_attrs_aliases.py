"""Conftest is executed by Pytest before test modules.

We use this to monkeypatch attrs.field(), so that we can detect if aliases are used for test_exports.
"""

from typing import Any

import attrs

orig_field = attrs.field


def field(**kwargs: Any) -> Any:
    if "alias" in kwargs:
        metadata = kwargs.setdefault("metadata", {})
        metadata["trio_test_has_alias"] = True
    return orig_field(**kwargs)


field.trio_modded = True  # type: ignore
attrs.field = field
