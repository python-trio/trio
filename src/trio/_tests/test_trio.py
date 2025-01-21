def test_trio_import() -> None:
    import sys

    for module in list(sys.modules.keys()):
        if module.startswith("trio"):
            del sys.modules[module]

    import trio  # noqa: F401


def test_trio_version_deprecated() -> None:
    import pytest

    import trio

    with pytest.warns(DeprecationWarning, match="^trio.__version__ is deprecated"):
        _ = trio.__version__
