"""Plugins are executed by Pytest before test modules.

We use this to monkeypatch attrs.field(), so that we can detect if aliases are used for test_exports.
"""

from typing import Any

import attrs

orig_field = attrs.field


def field(**kwargs: Any) -> Any:
    original_args = kwargs.copy()
    metadata = kwargs.setdefault("metadata", {})
    metadata["trio_original_args"] = original_args
    return orig_field(**kwargs)


# Mark it as being ours, so the test knows it can actually run.
field.trio_modded = True  # type: ignore
attrs.field = field
